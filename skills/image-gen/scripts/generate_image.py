#!/usr/bin/env python3
"""
Generate (or edit) images via ChatGPT's image_generation tool through the
backend Responses API, authenticating with OAuth tokens from
~/.codex/auth.json (Codex/ChatGPT login).

The ChatGPT backend uses a different API surface than api.openai.com:
  - Endpoint: https://chatgpt.com/backend-api/codex/responses
  - Auth: Bearer <access_token> + Chatgpt-Account-Id header
  - Format: SSE stream with image_generation tool calls
  - Response: base64 image data in response.output[].result

Two modes:
  - Generation (default): text-only prompt -> image
  - Style-anchored edit: --style-reference PATH sends a reference image;
    the tool action switches to "edit" and the image is embedded as a
    data URL in the input.

Preflight (--preflight):
  Runs auth diagnostics and a lightweight connectivity check. Surfaces
  every failure with an LLM-ready fix prompt so the calling agent can
  guide the user through resolution before attempting generation.

CLI:
  --prompt "..."           prompt text (or --prompt-file PATH)
  --prompt-file PATH       read prompt from a file
  --output PATH            output WebP path; directory is created if missing
  --size WxH               width x height (default 1536x1024)
  --quality LEVEL          low | medium | high | auto (default medium)
  --n COUNT                variations 1-10 (default 1); suffixed -1, -2, ...
  --style-reference PATH   reference image to anchor visual style (edit mode)
  --keep-png               also save raw PNG next to WebP
  --preflight              run auth diagnostics only, then exit
  --auth-file PATH         override default ~/.codex/auth.json
"""

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from io import BytesIO
from pathlib import Path
from typing import NoReturn

try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow (PIL) is required.", file=sys.stderr)
    print("Install with: pip install --user Pillow  (or: pacman -S python-pillow)", file=sys.stderr)
    sys.exit(2)


# ── Constants ────────────────────────────────────────────────────────────

VALID_QUALITY = {"low", "medium", "high", "auto"}
RESPONSES_MODEL = "gpt-5.4-mini"          # orchestrating text model
IMAGE_TOOL_MODEL = "gpt-image-2"           # actual image generator
BACKEND_URL = "https://chatgpt.com/backend-api/codex/responses"
TIMEOUT_SECONDS = 300
DEFAULT_AUTH_FILE = Path.home() / ".codex" / "auth.json"

STYLE_LOCK_PREFIX = (
    "Use the same visual style as the reference image (palette, lighting "
    "direction and quality, surfaces, depth of field, grain, color grading). "
    "Apply the new scene and subject described below. Preserve all visual "
    "invariants of the reference image.\n\n"
)


def die(message: str, code: int = 1) -> NoReturn:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(code)


# ── Preflight ────────────────────────────────────────────────────────────

def run_preflight(auth_file: Path) -> dict:
    """
    Check every prerequisite and return a diagnostic report.

    Returns a dict with:
      ok: bool          — all checks passed
      checks: list      — one entry per check; each has name, passed, message, fix
      auth_data: dict   — parsed auth.json (if readable)
    """
    report: dict = {"ok": True, "checks": [], "auth_data": {}}

    def check(name: str, passed: bool, message: str, fix: str = "") -> None:
        if not passed:
            report["ok"] = False
        report["checks"].append({
            "name": name,
            "passed": passed,
            "message": message,
            "fix": fix,
        })

    # 1. Auth file exists
    if not auth_file.exists():
        check("auth_file_exists", False,
              f"Auth file not found: {auth_file}",
              "Run `codex login` to create it, or pass --auth-file with the correct path.")
        return report
    check("auth_file_exists", True, f"Found: {auth_file}")

    # 2. Valid JSON
    try:
        data = json.loads(auth_file.read_text(encoding="utf-8"))
        report["auth_data"] = data
    except json.JSONDecodeError as err:
        check("auth_json_valid", False,
              f"Invalid JSON in {auth_file}: {err}",
              "The file is corrupt. Run `codex login` to regenerate it.")
        return report
    check("auth_json_valid", True, "Valid JSON")

    # 3. Access token present
    tokens = data.get("tokens", {})
    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")
    account_id = tokens.get("account_id", "")

    if not access_token:
        check("access_token_present", False,
              "No access_token in auth.json.",
              "Run `codex login` — the session has expired.")
    else:
        check("access_token_present", True, "access_token found")

    # 4. Token not expired
    if access_token:
        try:
            payload_b64 = access_token.split(".")[1]
            payload_b64 += "=" * (4 - len(payload_b64) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload_b64))
            exp = claims.get("exp", 0)
            now = time.time()
            if exp < now:
                check("token_not_expired", False,
                      f"Access token expired at {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(exp))}.",
                      "Token is expired but a refresh_token exists — the script will auto-refresh on first use. "
                      "If refresh fails, run `codex login`.")
            else:
                remaining = exp - now
                check("token_not_expired", True,
                      f"Token valid for {remaining:.0f}s (expires {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(exp))}).")
        except Exception:
            check("token_not_expired", True,
                  "Could not decode JWT expiry (non-fatal).")

    # 5. Refresh token present
    if not refresh_token:
        check("refresh_token_present", False,
              "No refresh_token in auth.json.",
              "Without a refresh token, an expired access token means re-login. Run `codex login`.")
    else:
        check("refresh_token_present", True, "refresh_token found")

    # 6. Account ID present
    if not account_id:
        check("account_id_present", False,
              "No account_id in auth.json.",
              "The ChatGPT backend requires this header. Run `codex login` to get a fresh session.")
    else:
        check("account_id_present", True, f"account_id: {account_id[:8]}…")

    # 7. Connectivity check — a lightweight ping that validates auth without
    #    spending image-generation credits. We send stream=true (backend
    #    requires it) with max_output_tokens=1 and tool_choice="none" so the
    #    model produces a near-zero-cost text completion instead of an image.
    if access_token and account_id:
        try:
            # Minimal request without image tools — validates auth without any
            # risk of consuming image-generation credits or hitting rate limits.
            ping_payload = json.dumps({
                "model": RESPONSES_MODEL,
                "instructions": "reply with ok",
                "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "ok"}]}],
                "stream": True,
                "store": False,
            }).encode()
            ping_req = urllib.request.Request(
                BACKEND_URL,
                data=ping_payload,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                    "Chatgpt-Account-Id": account_id,
                    "User-Agent": "Mozilla/5.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(ping_req, timeout=15) as resp:
                if resp.status == 200:
                    check("backend_reachable", True,
                          f"Backend reachable (HTTP 200) — auth valid.")
                else:
                    check("backend_reachable", False,
                          f"Unexpected HTTP {resp.status}.",
                          "Check the response body for details.")
        except urllib.error.HTTPError as err:
            body = err.read().decode("utf-8", errors="replace")[:500]
            if err.code == 401:
                check("backend_reachable", False,
                      "HTTP 401 — token rejected by backend.",
                      "The access token is invalid or expired. The script will attempt auto-refresh. "
                      "If that fails, run `codex login`.")
            elif err.code == 429:
                check("backend_reachable", True,
                      "HTTP 429 — rate limited. Backend reachable, auth valid.")
            elif err.code == 403:
                check("backend_reachable", False,
                      f"HTTP 403 — permission denied: {body[:200]}",
                      "Your ChatGPT account may not have access to the Responses API. "
                      "Check your subscription at https://chatgpt.com/account.")
            else:
                check("backend_reachable", False,
                      f"HTTP {err.code}: {body[:200]}",
                      "Unexpected response. Check your network and retry.")
        except urllib.error.URLError as err:
            check("backend_reachable", False,
                  f"Cannot reach chatgpt.com: {err.reason}",
                  "Check your internet connection. If you're on a VPN, verify "
                  "chatgpt.com is reachable.")
        except Exception as err:
            check("backend_reachable", False,
                  f"Connectivity check failed: {err}",
                  "Unexpected error. Retry or check your network.")

    return report


def print_preflight(report: dict) -> None:
    """Pretty-print the preflight report for human/LLM consumption."""
    print("\n" + "=" * 60, file=sys.stderr)
    print("  PREFLIGHT REPORT", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    for c in report["checks"]:
        icon = "✓" if c["passed"] else "✗"
        print(f"  {icon} {c['name']}: {c['message']}", file=sys.stderr)
        if not c["passed"] and c.get("fix"):
            print(f"    → FIX: {c['fix']}", file=sys.stderr)

    print("=" * 60, file=sys.stderr)
    if report["ok"]:
        print("  All checks passed.", file=sys.stderr)
    else:
        print("  Some checks failed. See FIX lines above.", file=sys.stderr)
    print("=" * 60 + "\n", file=sys.stderr)


# ── Auth ────────────────────────────────────────────────────────────────

def load_auth(auth_file: Path) -> dict:
    """Return the full auth.json data or die with a fix prompt."""
    if not auth_file.exists():
        die(
            f"Auth file not found: {auth_file}\n"
            "FIX: Run `codex login` to create it.",
            code=3,
        )
    try:
        return json.loads(auth_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        die(
            f"Invalid JSON in {auth_file}: {err}\n"
            "FIX: The file is corrupt. Run `codex login` to regenerate it.",
            code=3,
        )


def get_credentials(data: dict) -> tuple[str, str, str]:
    """Return (access_token, account_id, refresh_token_or_empty)."""
    tokens = data.get("tokens", {})
    access_token = tokens.get("access_token", "")
    if not access_token:
        die(
            "No access_token in auth.json.\n"
            "FIX: Run `codex login` — the session has expired.",
            code=3,
        )
    account_id = tokens.get("account_id", "")
    if not account_id:
        die(
            "No account_id in auth.json.\n"
            "FIX: The session data is incomplete. Run `codex login`.",
            code=3,
        )
    refresh_token = tokens.get("refresh_token", "")
    return access_token, account_id, refresh_token


def refresh_access_token(auth_file: Path, refresh_token: str) -> str | None:
    """Attempt OAuth refresh. Returns new access_token or None."""
    try:
        data = json.loads(auth_file.read_text(encoding="utf-8"))
    except Exception:
        return None

    id_token = data.get("tokens", {}).get("id_token", "")
    client_id = "app_EMoamEEZ73f0CkXaXp7hrann"  # from auth.json aud claim
    # Try to pull from id_token aud
    if id_token:
        try:
            payload_b64 = id_token.split(".")[1]
            payload_b64 += "=" * (4 - len(payload_b64) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload_b64))
            aud = claims.get("aud", [])
            if isinstance(aud, list) and aud:
                client_id = aud[0]
        except Exception:
            pass

    refresh_payload = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }).encode()

    req = urllib.request.Request(
        "https://auth.openai.com/oauth/token",
        data=refresh_payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
    except Exception:
        return None

    new_access = result.get("access_token")
    new_refresh = result.get("refresh_token")

    if not new_access:
        return None

    tokens = data.setdefault("tokens", {})
    tokens["access_token"] = new_access
    if new_refresh:
        tokens["refresh_token"] = new_refresh
    data["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%S.000000Z", time.gmtime())

    try:
        tmp = auth_file.with_suffix(auth_file.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(auth_file)
    except Exception:
        pass

    return new_access


# ── Validation ──────────────────────────────────────────────────────────

def validate_size(size: str) -> str:
    if size == "auto":
        return size
    try:
        w_str, h_str = size.lower().split("x")
        w, h = int(w_str), int(h_str)
    except (ValueError, AttributeError):
        die(f"Invalid --size: {size!r} (expected WxH, e.g. 1536x1024).")
    if w <= 0 or h <= 0:
        die(f"Invalid --size: dimensions must be positive (got {w}x{h}).")
    if w % 16 != 0 or h % 16 != 0:
        die(f"Invalid --size: both edges must be multiples of 16 (got {w}x{h}).")
    if w >= 3840 or h >= 3840:
        die(f"Invalid --size: max edge must be <3840 (got {w}x{h}).")
    if max(w, h) > 3 * min(w, h):
        die(f"Invalid --size: ratio must be <=3:1 (got {w}x{h}).")
    total = w * h
    if total < 655_360:
        die(f"Invalid --size: total pixels must be >=655360 (got {total}).")
    if total > 8_294_400:
        die(f"Invalid --size: total pixels must be <=8294400 (got {total}).")
    return f"{w}x{h}"


def validate_n(n: int) -> int:
    if n < 1 or n > 10:
        die(f"Invalid --n: must be between 1 and 10 (got {n}).")
    return n


def load_prompt(args: argparse.Namespace) -> str:
    if args.prompt and args.prompt_file:
        die("Pass --prompt OR --prompt-file, not both.")
    if args.prompt:
        return args.prompt
    if args.prompt_file:
        path = Path(args.prompt_file).expanduser()
        if not path.exists():
            die(f"Prompt file not found: {path}")
        return path.read_text(encoding="utf-8").strip()
    die("Either --prompt or --prompt-file is required.")


# ── Image helpers ───────────────────────────────────────────────────────

def image_to_data_url(image_path: Path) -> str:
    """Read an image and return a base64 data URL for the ChatGPT input."""
    if not image_path.exists():
        die(f"Style reference not found: {image_path}")
    data = image_path.read_bytes()
    ext = image_path.suffix.lower()
    mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".webp": "image/webp", ".gif": "image/gif"}
    mime_type = mime_map.get(ext, "image/png")
    return f"data:{mime_type};base64," + base64.b64encode(data).decode()


# ── API ──────────────────────────────────────────────────────────────────

def build_headers(access_token: str, account_id: str, stream: bool = True) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if stream else "application/json",
        "Chatgpt-Account-Id": account_id,
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Originator": "codex",
    }


def build_generate_request(prompt: str, size: str, quality: str) -> dict:
    """Build the ChatGPT Responses API request for image generation.

    The image_generation tool produces one image per call; the backend rejects
    a tool-level `n`, so multiple variations are handled by looping the call.
    """
    return {
        "model": RESPONSES_MODEL,
        "instructions": prompt,
        "input": [{
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": prompt}],
        }],
        "tools": [{
            "type": "image_generation",
            "action": "generate",
            "model": IMAGE_TOOL_MODEL,
            "size": size,
            "quality": quality,
            "output_format": "png",
        }],
        "tool_choice": {"type": "image_generation"},
        "stream": True,
        "store": False,
        "reasoning": {"effort": "medium", "summary": "auto"},
    }


def build_edit_request(prompt: str, size: str, quality: str,
                        reference_path: Path) -> dict:
    """Build the ChatGPT Responses API request with a reference image for style anchoring.

    One image per call; multiple variations are handled by looping the call.
    """
    data_url = image_to_data_url(reference_path)
    return {
        "model": RESPONSES_MODEL,
        "instructions": prompt,
        "input": [{
            "type": "message",
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": data_url},
            ],
        }],
        "tools": [{
            "type": "image_generation",
            "action": "edit",
            "model": IMAGE_TOOL_MODEL,
            "size": size,
            "quality": quality,
            "output_format": "png",
        }],
        "tool_choice": {"type": "image_generation"},
        "stream": True,
        "store": False,
        "reasoning": {"effort": "medium", "summary": "auto"},
    }


def parse_sse_response(raw: bytes) -> list[str]:
    """
    Parse an SSE stream from the ChatGPT backend.
    Collects output events and extracts base64 images from the final
    response.completed event.

    Returns a list of base64 image strings.
    """
    output_items: dict[int, dict] = {}
    fallback_items: list[dict] = []
    completed = None

    for line in raw.split(b"\n"):
        if not line.startswith(b"data: "):
            continue
        event_json = line[6:]  # strip "data: " prefix
        try:
            event = json.loads(event_json)
        except json.JSONDecodeError:
            continue

        ev_type = event.get("type", "")

        if ev_type == "response.output_item.done":
            item = event.get("item")
            if item:
                idx = event.get("output_index")
                if idx is not None:
                    output_items[idx] = item
                else:
                    fallback_items.append(item)

        elif ev_type == "response.completed":
            completed = event

    if completed is None:
        die("Backend stream ended without a response.completed event.", code=4)

    # Assemble final output list
    response = completed.get("response", {})
    outputs = response.get("output", [])

    # If the completed event has no output array, patch from collected items
    if not outputs and (output_items or fallback_items):
        outputs = [output_items[i] for i in sorted(output_items)]
        outputs.extend(fallback_items)

    # Extract images from image_generation_call items
    images: list[str] = []
    for item in outputs:
        if item.get("type") != "image_generation_call":
            continue
        result = item.get("result", "")
        if result:
            images.append(result)

    if not images:
        # Check for error in response
        error = response.get("error", {})
        if error:
            msg = error.get("message", str(error))
            die(f"Backend error: {msg}", code=4)
        die("Backend returned no images. The model may have refused the prompt.", code=4)

    return images


def call_api_with_retry(
    access_token: str, account_id: str, refresh_token: str,
    auth_file: Path, payload: dict,
) -> bytes:
    """
    POST to the ChatGPT backend and return the raw SSE response body.
    On 401, attempts token refresh and retries once.
    """
    token = access_token

    for attempt in range(2):
        body = json.dumps(payload).encode("utf-8")
        headers = build_headers(token, account_id, stream=True)
        req = urllib.request.Request(BACKEND_URL, data=body, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
                return resp.read()
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", errors="replace")[:800]

            if err.code == 401 and attempt == 0 and refresh_token:
                print("Access token expired, attempting refresh…", file=sys.stderr)
                new_token = refresh_access_token(auth_file, refresh_token)
                if not new_token:
                    die(
                        "Token refresh failed.\n"
                        "FIX: Run `codex login` to get a fresh session, then retry.",
                        code=3,
                    )
                token = new_token
                print("Token refreshed successfully.", file=sys.stderr)
                continue

            if err.code == 429:
                # Try to extract retry-after info
                try:
                    err_data = json.loads(detail) if detail.strip().startswith("{") else {}
                    error_info = err_data.get("error", {})
                    resets_in = error_info.get("resets_in_seconds", 0)
                    resets_at = error_info.get("resets_at", 0)
                    if resets_in:
                        mins = resets_in // 60
                        die(
                            f"Rate limit reached. Resets in {mins}min {resets_in % 60}s.\n"
                            f"FIX: Wait {mins // 60}h{mins % 60}m and retry. "
                            f"Or switch to --quality low for a lighter request.",
                            code=4,
                        )
                    if resets_at:
                        reset_time = time.strftime("%H:%M:%S", time.localtime(resets_at))
                        die(
                            f"Rate limit reached. Resets at {reset_time}.\n"
                            f"FIX: Wait until then and retry.",
                            code=4,
                        )
                except Exception:
                    pass
                die(
                    f"HTTP 429 — Rate limit reached.\n"
                    f"FIX: Wait a few minutes and retry. Your ChatGPT Team plan has "
                    f"usage caps that reset periodically.",
                    code=4,
                )

            die(f"HTTP {err.code} from backend: {detail[:500]}", code=4)

        except urllib.error.URLError as err:
            die(
                f"Cannot reach {BACKEND_URL}: {err.reason}\n"
                f"FIX: Check your internet connection. If you're on a VPN, verify "
                f"chatgpt.com is reachable.",
                code=4,
            )

    die("Unreachable.", code=4)


# ── Output ──────────────────────────────────────────────────────────────

def output_paths(base_output: Path, count: int) -> list[Path]:
    if count == 1:
        return [base_output]
    stem = base_output.stem
    suffix = base_output.suffix
    return [base_output.with_name(f"{stem}-{i + 1}{suffix}") for i in range(count)]


def save_webp(png_bytes: bytes, output_path: Path, keep_png: bool) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(BytesIO(png_bytes)) as image:
        image.load()
        image.save(output_path, format="WEBP", quality=88, method=6)
    if keep_png:
        png_path = output_path.with_suffix(".png")
        png_path.write_bytes(png_bytes)


# ── CLI ─────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate images via ChatGPT backend using Codex OAuth tokens.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--prompt", help="Prompt text (use --prompt-file for long prompts).")
    parser.add_argument("--prompt-file", help="Read the prompt from a file.")
    parser.add_argument("--output", required=True, help="Output WebP path (suffixed -1, -2, ... when --n > 1).")
    parser.add_argument("--size", default="1536x1024",
                        help="WxH (default 1536x1024). Edges <3840, multiples of 16, ratio <=3:1.")
    parser.add_argument("--quality", default="medium", choices=sorted(VALID_QUALITY))
    parser.add_argument("--n", type=int, default=1, help="Variations (1-10, default 1).")
    parser.add_argument("--style-reference", help="Reference image for visual style anchoring.")
    parser.add_argument("--keep-png", action="store_true", help="Also save raw PNG next to WebP.")
    parser.add_argument("--preflight", action="store_true", help="Run auth diagnostics only, then exit.")
    parser.add_argument("--auth-file", default=str(DEFAULT_AUTH_FILE),
                        help=f"Path to Codex auth.json (default: {DEFAULT_AUTH_FILE}).")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    auth_file = Path(args.auth_file).expanduser()

    # ── Preflight ──
    if args.preflight:
        report = run_preflight(auth_file)
        print_preflight(report)
        return 0 if report["ok"] else 1

    # Always run a quick preflight before generation
    report = run_preflight(auth_file)
    if not report["ok"]:
        print_preflight(report)
        die(
            "Preflight failed. Fix the issues above and retry.\n"
            "Tip: Run with --preflight to diagnose without attempting generation.",
            code=3,
        )
    print("Preflight passed.", file=sys.stderr)

    # ── Parse inputs ──
    size = validate_size(args.size)
    n = validate_n(args.n)
    prompt = load_prompt(args)
    if not prompt.strip():
        die("Prompt is empty.")

    auth_data = report["auth_data"]
    access_token, account_id, refresh_token = get_credentials(auth_data)

    output_path = Path(args.output).expanduser().resolve()
    paths = output_paths(output_path, n)

    # ── Build request factory ──
    if args.style_reference:
        reference_path = Path(args.style_reference).expanduser().resolve()
        wrapped_prompt = STYLE_LOCK_PREFIX + prompt
        print(
            f"Calling ChatGPT backend (edit): size={size} quality={args.quality} n={n} "
            f"reference={reference_path.name}",
            file=sys.stderr,
        )
        make_payload = lambda: build_edit_request(wrapped_prompt, size, args.quality, reference_path)
    else:
        print(
            f"Calling ChatGPT backend (generate): size={size} quality={args.quality} n={n} "
            f"prompt={prompt[:80]}{'…' if len(prompt) > 80 else ''}",
            file=sys.stderr,
        )
        make_payload = lambda: build_generate_request(prompt, size, args.quality)

    # ── Call API (the tool returns one image per call; loop for variations) ──
    b64_images: list[str] = []
    for i in range(n):
        if n > 1:
            print(f"Requesting image {i + 1}/{n}…", file=sys.stderr)
        print("Waiting for response (this may take 30-120s)…", file=sys.stderr)
        raw = call_api_with_retry(access_token, account_id, refresh_token, auth_file, make_payload())
        b64_images.append(parse_sse_response(raw)[0])
    print(f"Received {len(b64_images)} image(s).", file=sys.stderr)

    # ── Save ──
    for b64_str, target in zip(b64_images, paths):
        png_bytes = base64.b64decode(b64_str)
        save_webp(png_bytes, target, args.keep_png)
        size_kb = len(png_bytes) // 1024
        print(f"OK {target} ({size_kb}KB)", file=sys.stderr)
        print(str(target))

    return 0


if __name__ == "__main__":
    sys.exit(main())
