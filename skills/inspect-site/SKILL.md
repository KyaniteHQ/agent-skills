---
name: inspect-site
description: Live-site reconnaissance via chrome-devtools MCP. Drive a real, attached browser to observe how a target web app actually works — network requests, API endpoints, request/response shapes, DOM structure, console — so behavior is VERIFIED, not assumed. Use before claiming/coding/debugging anything about a site's pages or requests, when asked to inspect/trace a site, find what endpoint a form or button hits, capture a request/response shape, or check the live DOM contract before touching a scraper, browser-automation, or API integration.
---

# inspect-site

Reconnaissance for a target web app so it is **not a black box**: observe the real requests, endpoints,
payload shapes, DOM, and console **before** claiming, coding, or debugging. Chrome DevTools is the cheap
**structural** lens — but if the thing you ship runs through a *different* path (a stealth browser, a
server-side HTTP client, a mobile app), structural truth is **provisional** until confirmed there.
**Every recon claim carries an explicit truth-level label.**

## Truth levels — pick the lowest one that answers the question

| Level | Lens | Authoritative for | Label |
| --- | --- | --- | --- |
| **1. Structural** | chrome-devtools MCP attached to a **real** browser | DOM, form mechanics, endpoint discovery, rough request sequence, request/response *shapes* | **structural (non-production)** |
| **2. Engine-observed** | the project's actual production fetch path (its real client / stealth engine / SDK), driven minimally | how the production client behaves: path selection, anti-bot handling, auth, headers that matter | **engine-observed** |
| **3. Production-validated** | the full end-to-end pipeline run | the real outcome: persisted result, downstream acceptance, retries/failures | **production-validated** |

**Rule:** a claim about *production behavior* is only **true** once it is engine-observed or
production-validated. Structural (Chrome) claims are **provisional** — say so. Chrome shows *structural*
truth (endpoints, payload shapes, DOM ids), **not** how a different production client is treated (anti-bot
systems often fingerprint the browser/TLS, so what Chrome sees ≠ what a server-side client or a different
browser sees). If the project doesn't have a separate production path, Level 1 may be the whole story —
state that explicitly.

## Preflight (fail-closed — run every session)

1. **Confirm the chrome-devtools MCP tools exist** before calling them (`list_pages`, `navigate_page`,
   `list_network_requests`, `get_network_request`, `take_snapshot`, `list_console_messages`,
   `evaluate_script`). If unavailable, **stop** — do not call tools that may not exist.
2. **Attach to a REAL, user-started browser** (see below), never the MCP's own self-launched profile.
   Call `list_pages`; it **must** show that browser's real tabs. Many sites silently block
   tool-launched / headless browsers, so a blank or self-launched browser means your recon is invalid —
   **STOP** and attach a real one.

### Attach a real browser

Drive a real, user-started browser via remote debugging. Pick one, then re-run preflight:

- **Chromium/Brave remote debugging:** enable at `chrome://inspect/#remote-debugging` (Brave:
  `brave://inspect/#remote-debugging`); it reports a server (commonly `127.0.0.1:9222`). Point the MCP at
  it with `--browser-url=http://127.0.0.1:9222`. Use the **port the browser reports** and verify with
  `list_pages`.
- **Dedicated launch (no inspect UI):** `google-chrome-stable --remote-debugging-port=<free-port>
  --remote-debugging-address=127.0.0.1 --user-data-dir=<non-default-dir>` (avoid IPv6 `[::1]`), then
  `--browser-url=http://127.0.0.1:<free-port>`.

**Security caveat:** remote debugging grants the MCP **full control** of that browser — its cookies, saved
data, and any navigation. Use a **dedicated profile/instance** for recon, not your personal browsing
profile.

## Observational workflow (Level 1)

**Observational capture only.** Do NOT use request interception (`Fetch.enable` / `page.route`) on a live
flow you only want to *watch* — on some sites it stalls navigation. Passive `Network`-domain observation is
safe.

1. `navigate_page` → the target URL.
2. Baseline with `list_network_requests`.
3. Drive the page (fill the form / click the button) the way a real user would; prefer the page's native
   input events. If a value is sensitive (a credential, an account id, a token), **inject it at runtime
   from your secret manager — never paste it into this skill or any file.**
4. Capture: `list_network_requests` (locate the endpoint of interest), `get_network_request`
   (request/response bodies → a temp dir, see below), `take_snapshot` (a11y DOM), `list_console_messages`.
5. Read the result signal off the live page (URL change, an element appearing/disappearing). Label findings
   **structural**.

## Capture hygiene (when bodies may carry secrets/PII)

- Save response bodies to a `mktemp -d` dir at **mode 0700** — never a fixed path, never inside the repo.
- Print a cleanup reminder for that temp dir at the end.
- Inject any sensitive input at runtime from your secret manager — never hardcode it.
- **Never** copy raw bodies that carry secrets/PII into repo docs, logs, tickets, or chat — only redacted
  shapes / hashed forms. Endpoints, headers, and payload **shapes** are fine; payload **values** that carry
  secrets/PII are not.

## Output (no auto-write)

- Answer in chat. **Tag every claim with its truth level** (structural / engine-observed /
  production-validated).
- Writing findings into project docs is a **separate, explicit phase** — never an automatic write after a
  capture. Summarize the redacted evidence, propose where it belongs (a DOM/contract doc vs an operational
  notes doc), show the **redacted diff**, and write **only on explicit go**. A one-off observation is not
  fossilized as a present-tense contract.

## Guardrails recap

- Chrome is structural-only; production behavior needs Level 2/3. Label everything.
- Fail closed if the MCP isn't attached to a real external browser.
- No request interception on a flow you only want to observe.
- No raw secrets/PII in any file/doc/log/ticket/chat. Captures live in a 0700 temp dir only.
