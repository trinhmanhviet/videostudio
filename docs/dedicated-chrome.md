# Dedicated headed Chrome for VideoStudio

## Approved scope
Use the user's ChatGPT account through an isolated Chrome profile on D:, not an API or extension. Headless is deferred. Personal Chrome is not modified, restarted, or used as a source of cookies.

## Launch
- Run `powershell -NoProfile -File scripts/start_local.ps1` to start the UI and passive browser service.
- Open `http://127.0.0.1:8877/` and use **Mở Chrome riêng / đăng nhập**, or run `powershell -NoProfile -File scripts/start_browser.ps1`.
- Profile defaults to `D:\Projects\videostudio\data\chrome-profile`. Profile, cookies, requests and service logs stay in ignored `data/`.
- Chrome is launched with a loopback ephemeral debug port and an explicit non-default user-data-dir. There is no wildcard remote-allow-origins flag, copied login database, or default-profile DevToolsActivePort lookup.
- On first use the owner signs in within this separate window. Do not request passwords in chat or automate login/CAPTCHA/2FA.
- Existing daemon/server restarts require explicit script switches and refuse non-owned ports or active jobs. Health/status checks are read-only and never start Chrome or initiate CDP.

## Request and lifecycle model
One CDP receiver dispatches replies by ID, not recv-per-command. Browser start/connect is single-flight. Tabs are allocated per job and persisted; arbitrary user tabs are never selected. Missing/closed owned tabs are recreated using the saved conversation URL. Context errors fail explicitly instead of parsing an empty response.

Requests have durable IDs derived from job+prompt hash. Send intent is committed before mouse input. A response must follow the matching user marker and carry the exact request_id envelope. Completed replies are cached and immutable. If delivery was attempted but the result is unknown, retries only inspect the saved conversation; they never blindly resend or fall back to the extension. This prefers an honest blocked job to duplicate messages.

The daemon exposes `/api/status` (passive GET), `/api/browser/start`, `/api/browser/probe`, and `/api/chat`. Mutation endpoints reject foreign Host/Origin, require JSON and the X-VS-Client header, and provide no permissive CORS. VideoStudio proxies setup controls on port 8877.

## Actual verification in this change
- Launcher tests: isolated profile, loopback ephemeral port, no wildcard origin/headless, reject personal profile, stale endpoint/token validation, process reuse.
- CDP protocol tests use a real local WebSocket server to check interleaved events, concurrent IDs, errors, disconnect and timeout cleanup.
- Request journal tests cover restart retention, no second send, immutable response and marker matching.
- Daemon/API tests cover passive health, cross-origin rejection, scoped job IDs, cached reply and owned-target replacement.
- `scripts/verify_dedicated_browser.py` ran against real Chrome using about:blank fixture tabs: attested own profile, native Vietnamese input and mouse click, close detection and reconnect to the same browser. It sent zero ChatGPT requests. Evidence: `data/dedicated-browser-live.json`.

## Not yet accepted
Live ChatGPT login, DOM adaptation/send/receive, browser Memory Saver/discard recovery, and a new complete video have NOT been accepted in this change. A connected socket is not production acceptance. The main preflight requires verified authentication and a real correlated `__acceptance__` smoke reply before releasing new production jobs. The setup **Kiểm tra đăng nhập** button checks login only; a separate supervised smoke test is still required.

The full regression currently has three failing pre-existing dirty-worktree GPU ownership tests. This connector change does not stage/rewrite gpu.py or the earlier Comfy unload modifications in providers.py. GPU sequencing and CUDA TTS remain a separate validation track, not silently claimed complete. Authentication interruptions during an active job retain receipts but automatic resumption of every failed job is not accepted yet.
