# AICoworker WebAuth ChatGPT text transport

This is a **separate, selectable** text-only transport. It reads AICoworker's current local WebAuth proxy URL from `~/aicoworker/openclaw/openclaw.json` at request time, requires the `webauth-chatgpt-gpt` model to appear on `/v1/models`, and parses the proxy's SSE completion into a JSON object. It does not copy cookies, start Chrome, use the dedicated VideoStudio CDP daemon, or replace image generation (Flow/Comfy remain separate).

To start the Studio UI in this mode from a stopped server:

```powershell
cd D:\Projects\videostudio
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_local.ps1 -TextTransport webauth
```

Do **not** press **Mở Chrome riêng** for this text transport. That button still launches the separate CDP browser for legacy features. The startup command with no `-TextTransport` remains CDP mode. If port 8877 is already occupied by a VideoStudio server, the script refuses a second server; switching transport requires an idle-only restart with `-RestartOwnServer`, which may interrupt active work and must be done only after checking jobs.

Preflight requires live WebAuth model availability and an exact completed synthetic text smoke receipt. A smoke can be run explicitly once with `PYTHONPATH=D:\Projects\videostudio` and `python scripts\verify_webauth_text.py`; it sends one short synthetic prompt through the signed-in WebAuth session. On an error or unexpected answer no receipt is written and production remains locked; **do not automatically retry** a request that may have reached ChatGPT. A transport failure is terminal for the job rather than falling into Core's generic retry loop.

Limitations: WebAuth does not attest ChatGPT High or live Web Search, so factual research remains unverified and prompts must say so. The proxy's web session can expire or challenge authentication. This adapter does not solve CAPTCHA and does not offer durable request correlation equivalent to the older CDP journal. WebAuth text transport should not be described as a verified end-to-end video pipeline until the smoke and a controlled complete job pass.
