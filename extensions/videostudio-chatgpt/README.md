# VideoStudio ChatGPT Bridge (isolated, text only)

## Version 0.3.9: user-operated recovery from the floating manager

Each pending/failed text video has **Khôi phục ChatGPT**. The inline panel finds an exact existing reply, reopens the saved conversation in an inactive ordinary-Chrome tab when needed, or asks for a conversation URL when older state has none. The URL must be a ChatGPT conversation and its visible immutable marker must match before rebinding/import. It never sends a prompt. After verified rebinding, obsolete tool-owned tabs for that request are closed; other sessions stay untouched. Login/unreadable/ambiguous cases show actionable instructions and **Mở ChatGPT**, without manufacturing a reply or repeatedly opening tabs.

A recovered accepted response can resume a connector-failed text stage once, including when the server timeout races with import. Already-accepted receipts are checked before attempting continuation. Completed/cancelled videos and other failure types are not silently restarted. Explicit recovery preserves scope/request/version/attempt and existing checkpoints. No additional Chrome permissions or backend restart.

User instructions: [self-service recovery](../../docs/self-service-chatgpt-recovery.md). Reload extension and Studio once to install this UI; ordinary later recovery uses the float. Verification: 98 Node tests, 30 offline Chromium manager cases (including self-service import/retry, pasted URL and login guidance), and the completed-reply renderer fixture. The current owner's tab was not operated by the agent because the computer-use runtime could not initialize.

## Version 0.3.8: recover a closed/frozen ChatGPT tab

Reconciliation has a three-second renderer timeout. When the original tab is unavailable, it can find a replacement conversation tab and bind the pending request to it only after matching the immutable request marker. A saved conversation URL further restricts candidates; old persisted state without a URL can recover by a unique exact marker. Other jobs' tabs, unrelated conversations and ambiguous duplicate matches are rejected. Inspections never click Send or create a tab. A previously sent request with an unavailable tab is retained for recovery, not blindly sent again. Match-only inspection returns no unrelated user/reply text.

Reload this extension, reload the replacement ChatGPT conversation tab, then reload Studio. Press Start only if disconnected; the existing bridge/requests must be preserved. Read-only recovery runs on the existing timer and Check again action. No backend restart or new smoke is required by this change. Existing import/cleanup rules apply after successful receipt acceptance.

Verified: 94 Node tests, including missing/frozen tabs, unique-marker discovery for old saved state, foreign URLs/markers, ambiguous tabs and no resend; `node scripts/test_replacement_tab.cjs` runs the shipped worker/content script with a completed JSON conversation in offline Chromium. Not yet confirmed against the owner's live replacement tab; the computer-use runtime failed initialization, so its URL/reply were not read directly.

## Version 0.3.7: retry an ineffective Send click

After inserting the prompt and clicking Send, retry the current enabled Send control at most twice, after approximately 5 and 10 seconds without a user receipt. This only continues while the owned request marker remains in the composer, with no user/assistant turn or generation indicator. Once that evidence changes, retries stay disabled for the request. There is no prompt length/full-content comparison; the previous guards remain commented for later investigation. Background tabs remain inactive. Timers may be throttled by Chrome.

Reload this extension in `chrome://extensions`, then reload Studio. No backend restart is required. Existing already-dispatched ChatGPT tabs keep their old content script until reloaded; this update takes effect on subsequent fresh request tabs and does not automatically resend historical uncertain requests.

Verified with the send-button/send-recovery Node tests and `node scripts/test_send_recovery.cjs`, which runs the shipped scripts in offline Chromium fixtures for an ignored click, cleared/replaced drafts, aria-disabled Send, and delayed receipt. This is not a live-account confirmation.

## Version 0.3.3: real connection readiness

The service worker maintains the real connected root's heartbeat through a named Chrome alarm every 30 seconds, independent of throttled Studio page timers. It checks that the owner tab still exists at the exact connected production URL; Stop, a closed tab or another page cannot renew the heartbeat. The manifest adds only the `alarms` permission; existing host access stays unchanged. The backend uses a consistent 90-second freshness window and exposes transport and latest correlated smoke as separate readiness checks with actionable messages.

For a fresh tool-owned conversation, the content script selects the visible **Chat** control when needed and verifies its selection using aria-pressed/aria-selected/aria-checked (or active tab state), before typing and again before Send. It still refuses login/challenge/unknown-mode requests. A previous exact mode error known to happen before Send may recover once using the original request and existing retry budget; after-Send or ambiguous errors are not reclassified as safe unsent work.

Cancelled/cancel-requested videos disappear from the floating panel and its video error count. Their immutable server receipts and internal cancellation state remain available to prevent duplicate sends and finish local cleanup; no video files are deleted.

After backend update, reload extension **0.3.3**, reload the connected Studio page and press Start only if it has not reconnected. The page can automatically reconcile the existing pre-Send mode-failed Test request; it does not require manufacturing a new smoke or deleting extension storage. Keep the owner Studio tab open. `/api/connector/bridges/{root}/status` reports authoritative heartbeat and latest-smoke diagnostics.

Integrated verification: `node scripts/test_extension_connection_e2e.cjs` runs the shipped content script and worker against a real isolated FastAPI/SQLite backend, with intercepted ChatGPT fixture pages and fixture-only media prerequisites. It verifies Work→Chat, exact receipt import, worker-origin heartbeat acceptance, all preflight checks becoming ready, and recovery of the prior unsent mode-failed smoke without duplicate Send. It never accesses the owner's account.

## Version 0.3.2: Start reconnects the saved bridge

Start first discovers the extension's saved bridge metadata and checks that root still exists on the local server. If one exists, it reconnects the current Studio tab and returns to that bridge's production page, preserving all video slots, receipts, tabs and attempts. It does not allocate a new scope just because the owner opened the homepage or another scoped page. The page being left cannot heartbeat a foreign scope. Only a first connection without saved state creates a root. Connection discovery exposes no prompt/session data and rejects foreign origins or unsupported pages.

Reload extension 0.3.2 and reload Studio, then click Start. Existing pending videos do not need to be deleted or cancelled. Backend/heartbeat protocol remains 0.3.0, so no server restart or new synthetic smoke is required for this extension change.

## Version 0.3.1: long-prompt Send and correlated recovery

After repairing/truncated chunk insertion, the content script now resolves the current enabled Send control again, then rechecks the exact prepared composer before its one click. A replaced composer is rejected. Background recovery and content-script turn recognition share the same request-marker/normalised-text matcher in `logical-text.js`; a collapsed user bubble can recover its completed reply, while another ID with the same prefix cannot match.

Reload the extension in `chrome://extensions`, then **reload the connected Studio tab**. If it does not reconnect automatically, press Start on the newly loaded page. A dead content script cannot be revived by clicking its old Start button. Version 0.3.1 keeps the 0.3.0 heartbeat protocol so the backend needs no restart. No smoke reply or heartbeat is generated by these code changes.

## Current: version 0.3.0, multiple queued video sessions

Reload this extension in `chrome://extensions`, then reload the existing connected Studio tab. Its original bridge root and accepted text smoke are preserved. New videos receive independent child scopes; a failed/completed previous video does not reserve the whole bridge. Each scope retains its own request IDs, receipt, retry count and owned background tab. The backend requires a fresh 0.3.0 heartbeat before accepting new child jobs; older extensions receive an explicit reload message rather than silently missing requests.

The floating manager lists video name, pipeline stage and ChatGPT state. Use **Mở chat** for an explicit tab switch, **Kiểm tra lại** for read-only inspection of the same old request, or **Hủy** for that video alone. Shrink the panel to a round button with active/error badges; shrinking does not stop polling, and the choice survives reload. Keep the owner Studio tab open. **Stop** pauses the connection across its slots; it does not claim to cancel video jobs or website-side generation.

Legacy root-bound videos remain listed. An explicit connection smoke can retain a terminal legacy video's previous request locally while handling the new smoke separately; it cannot overwrite the old receipt or reset attempts. Historical Open/Check actions carry the exact old request ID. Late callbacks cannot cross slots, and cancelled/completed/failed video requests are not automatically dispatched as new work.

This release accepts multiple video jobs and manages their queue. It does **not** implement simultaneous video generation: see `D:\Projects\videostudio\TODO.md`. Worker/media/GPU scheduling remains serial. Every automatic ChatGPT tab, including a bounded retry, stays in the background.

Verification commands: `node --test extensions/videostudio-chatgpt/tests/*.test.mjs tests/*.test.mjs`, `node scripts/test_extension_manager_ui.cjs`, `node scripts/test_extension_bridge_ui.cjs`. Fixture tests do not use the signed-in account or generate production media.

This unpacked MV3 extension is separate from StoryForge. It uses ordinary Chrome without debugging/automation flags, cookie access or ChatGPT private APIs. The person handles ChatGPT sign-in and verification. Flow/Comfy remains separate.

Start VideoStudio with `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_local.ps1 -TextTransport extension` from the repository root. Load this folder as an unpacked extension in the ordinary Chrome profile. Open `http://localhost:8877/` and click **Start once**. The extension creates a local scope, activates the bridge on that same Studio tab and navigates to the scoped production page. It rehydrates automatically; no second Start. Click **Test chữ** once for the text-only smoke. Each new exchange opens a dedicated fresh ChatGPT conversation/tab. Do not type in owned tabs. **Stop** disables polling/heartbeat and closes only tabs created by this extension; an already submitted server exchange remains pending for audit.

A request's immutable marker, version and attempt are correlated with the exact visible user turn and assistant reply before import. On an uncertain send or a bounded response timeout, the worker checks the server receipt and previous owned tab first. If the old reply is complete it imports that instead; otherwise it may retry **once only** in another fresh tab. An uncertain prior send may duplicate a question on the website; this is a bounded, user-requested risk, not true idempotence. Auth/CAPTCHA/unknown mode stops for the person, never auto-retries. A stopped unresolved exchange is not erased from the server.

After reloading an updated extension, reload the Studio page once if its old content script reports an invalidated context. Open `http://localhost:8877/` and use one Start to create a fresh scope, then one Test chữ. Each test creates a new exchange and a fresh ChatGPT tab. If the previous prompt still appears in an old tab's composer without a sent user turn, do not press Send there. The composer-text check reads ProseMirror paragraphs as logical newlines (the site's `innerText` inserts extra layout newlines), so a visually exact prompt is not rejected before clicking Send. There is no manual Discard button and no two-click Start. Real Chrome/ChatGPT smoke has **not** been run for version 0.2.1; the owner must supervise the first synthetic prompt before production use. The ChatGPT DOM may change. Do not claim the rest of the VideoStudio preflight or video pipeline is verified from this bridge alone.

## Version 0.2.1: ordinary Chrome startup and recovery

1. Run `powershell -NoProfile -File scripts/start_extension.ps1` from the repository root. If an idle VideoStudio server already occupies 8877, use `-RestartOwnServer`; its existing idle/ownership checks still apply. This starts no CDP daemon or separate browser.
2. In ordinary Chrome, open `chrome://extensions` and reload the existing **VideoStudio ChatGPT Bridge**. For a first installation, use Load unpacked and select `D:\Projects\videostudio\extensions\videostudio-chatgpt`.
3. Open **http://localhost:8877/** (the extension deliberately does not match `127.0.0.1`), click **Start**, then **Test chữ** once. Keep the scoped Studio tab open. ChatGPT must be signed in and in Chat mode. Login/challenges require the person.
4. The scoped form locks text generation to ChatGPT through the bridge. Gemini cannot silently send a job to the dedicated CDP browser. Image providers are separate: Flow/ChatGPT image generation still requires their existing dedicated-browser integration; ComfyUI remains local. This release changes text transport only.

The worker serializes persistent state transitions, probes the content script before delivery, and waits for both the exact composer text and an enabled Send button. Delivery and reload recovery now share the same exact-turn/completion checks, including modern ChatGPT markup, duplicate markers and visible streaming state. Temporary Studio network errors reconnect without another Start. Extension invalidation still requires one Studio reload.

Stop closes owned tabs and suspends the pending receipt locally. Start on the same scoped page restores its original attempt count; it cannot reset the one-retry budget. A deliberate Start from the root creates a different scope and archives the prior receipt. An exhausted or authentication-blocked exchange remains visible for inspection; it is never declared successful because its budget ran out. The server waits up to 900 seconds per extension text call to cover both bounded browser attempts.

Tests: `node --test extensions/videostudio-chatgpt/tests/*.test.mjs` and `node scripts/test_extension_bridge_ui.cjs`. The UI test uses real local Chromium with intercepted fixture pages and a simulated extension runtime, never the signed-in ChatGPT website. It does not prove a live account smoke or a full video generation run.

## Version 0.2.2: background ChatGPT tabs

Both initial delivery and the one bounded retry now create ChatGPT tabs with `active: false`. No tab/window activation or focus-restoration step is used. The content script's composer focus stays inside its own hidden document. If authentication or an unsupported mode blocks the request, the bridge retains its existing blocked state; it does not bring the tab forward automatically. Open that tab yourself when intervention is needed.

Reload the extension in `chrome://extensions`, then reload the Studio page once. No backend restart is required for this update over 0.2.1: the compatible heartbeat protocol identifier remains `videostudio-extension-0.2.1`. The owner has already configured Chrome to keep ChatGPT active; this update changes no sleep/performance settings.

Run `node scripts/test_extension_background.cjs` for a headed Chrome renderer check with a separate fresh test profile and intercepted pages. The test avoids Playwright's automatic focus emulation and background-throttling overrides; its test-only CDP connection never touches the owner's browser. It verifies `visibilityState === 'hidden'`, `hasFocus() === false`, one Send, received/recoverable reply, and unchanged foreground input/focus. Evidence is written to `data/extension-background/verification.json`. This short fixture check does not establish live ChatGPT compatibility, long-idle timer behavior, or operation while Chrome/the computer is closed/asleep.

Run `node --test extensions/videostudio-chatgpt/tests/*.test.mjs` from the repository root for unit/runtime-fixture tests.
