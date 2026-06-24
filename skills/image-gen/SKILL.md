---
name: image-gen
description: Generate or edit images via ChatGPT's image_generation tool, authenticating with OAuth tokens from ~/.codex/auth.json (Codex/ChatGPT login) — no API key needed, just an active Codex login. Use whenever the user wants to create, generate, render, draw, or edit an image: "generate an image", "create a hero image", "make a photo of X", "draw X", a style-anchored edit, or running preflight diagnostics on the image-gen setup. Backed by gpt-image-2; see references/prompting-tips.md for prompt craft.
---

# Image Generation (via the ChatGPT/Codex backend)

Generate and edit images through the ChatGPT backend Responses API
(`chatgpt.com/backend-api/codex/responses`) with the `image_generation` tool — the same API the ChatGPT
web UI uses internally. Authenticates with the OAuth tokens from `~/.codex/auth.json`, so **no separate
API key is needed**: if Codex is logged in, images work.

The helper lives at `${CLAUDE_SKILL_DIR}/scripts/generate_image.py` (Python 3.8+ stdlib + Pillow only).
For prompt craft (structure, photorealism, text, editing, per-use-case shortcuts), read
[`references/prompting-tips.md`](references/prompting-tips.md).

## Always run preflight first

Before generating, run diagnostics to catch auth issues early:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/generate_image.py --preflight --output /dev/null
```

This checks: auth.json exists, valid JSON, access_token present and not expired, refresh_token present,
account_id present, backend reachable. Every failure includes an LLM-ready `FIX:` line — read it and guide
the user. Exit 0 = all clear. The preflight also runs automatically before every generation; if it fails,
the script prints the report and exits before spending any credits.

## Generating images

```bash
SCRIPT="${CLAUDE_SKILL_DIR}/scripts/generate_image.py"

# Basic generation
python3 "$SCRIPT" \
  --prompt "a vintage typewriter on a wooden desk, soft window light, photorealistic" \
  --output ./typewriter.webp

# Multiple variations  → typewriter-1.webp, -2.webp, -3.webp
python3 "$SCRIPT" --prompt "studio shot of a ceramic coffee cup, white background" --n 3 --output ./cup.webp

# Read prompt from a file
python3 "$SCRIPT" --prompt-file ./hero-prompt.txt --output ./hero.webp

# Style-anchored edit (match a reference image's visual style)
python3 "$SCRIPT" --prompt "a bowl of soup on a rustic wooden table" \
  --style-reference ./anchor-hero.webp --output ./soup-hero.webp

# Keep the raw PNG too
python3 "$SCRIPT" --prompt "a sunset over the bay" --output ./sunset.webp --keep-png
```

## How it works

The script calls `https://chatgpt.com/backend-api/codex/responses` (the ChatGPT backend, NOT
`api.openai.com/v1`) with:

- **Auth**: `Authorization: Bearer <access_token>` + `Chatgpt-Account-Id: <account_id>`, both from
  `~/.codex/auth.json`. On 401 the script auto-refreshes the token via OAuth and writes the new tokens back.
- **Model**: `gpt-5.4-mini` (orchestrating text model) calls the `image_generation` tool backed by
  `gpt-image-2`. The tool returns one image per call; `--n` loops the call.
- **Response**: SSE stream → `image_generation_call` outputs → base64 PNG → saved as WebP (Pillow). Response
  time is typically 30-120s.

## Error handling

Every error carries a `FIX:` line. Key exit codes: `1` bad args; `2` missing Pillow
(`pip install --user Pillow`); `3` auth broken (`codex login`); `4` API error (429 = rate limit,
401 = expired token → auto-refresh attempted).

## Size & quality

`gpt-image-2` (validated before the call): edges <3840, multiples of 16, ratio ≤3:1, 655k-8.3M px total.
Common: `1024x1024` (square), `1536x1024` (landscape, default), `1024x1536` (portrait), `2560x1440` (16:9).
Quality: `low` (ideation/batch), `medium` (default), `high` (close-ups, fine detail, final), `auto`.

## Dependencies

```bash
pip install --user Pillow   # or: pacman -S python-pillow
```

## When NOT to use this skill

- **Non-OpenAI providers** (Stability, Replicate, Gemini, Midjourney): this skill only talks to the
  ChatGPT backend.
