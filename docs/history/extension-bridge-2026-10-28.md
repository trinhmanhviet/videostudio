# Ordinary-Chrome extension bridge 0.2.1

The existing extension at `extensions/videostudio-chatgpt` remains the text bridge in the user's ordinary Chrome. Launch with `powershell -NoProfile -File scripts/start_extension.ps1`. For an already running, idle, owned VideoStudio server, add `-RestartOwnServer`. Reload the existing extension in `chrome://extensions`, reload/open `http://localhost:8877/`, click Start and then Test chữ. Keep the scoped Studio page open and ChatGPT in Chat mode.

## Corrected failures

- Per-job `text_provider` used to overwrite the explicit extension transport with CDP. ChatGPT now honors the selected extension transport; incompatible Gemini jobs are rejected before allocation. The scoped form selects and locks ChatGPT.
- Concurrent MV3 handlers could open two tabs for one claim or overwrite Stop/a completed reply with late state. State transitions are now serialized and completed replies cannot regress to uncertain.
- Stop/Start, including repeated Stop, preserves the suspended receipt and attempt count. Starting a deliberately new scope from the root remains an explicit new session.
- Tab completion did not prove a content script was listening. The worker now probes before dispatch. The content script waits for the composer, the exact logical prompt and enabled Send, without inserting or sending twice.
- Reload recovery used a narrower selector/completion rule than live delivery, could miss modern completed turns and could import a partial response with feedback controls. Both paths now share exact-turn correlation, modern selectors, duplicate detection and streaming/completion checks.
- Temporary network errors permanently stopped polling. Both direct Studio API errors and worker receipt-fetch errors now retain transient classification and reconnect. Receipt/Studio fetches have a 15-second deadline.
- Backend text requests timed out after 180 seconds despite up to two six-minute browser attempts. Extension calls now wait up to 900 seconds for the same durable exchange.
- A duplicate smoke request raised HTTP 500 because the API omitted the `PermanentError` import; it now returns HTTP 409 without creating a second pending request.

## Verification

- Python: `C:\Python312\python.exe -m unittest discover -s tests -p 'test_*.py' -q` — 312 tests, OK, 51.184 seconds. API/socket tests ran outside the Windows sandbox after its internal socketpair blocked; the run used an isolated import DB, temp directory and voice root under `data/test-tmp`. Log: `data/extension-python-regression.txt`.
- Extension: `node --test extensions/videostudio-chatgpt/tests/*.test.mjs` — 26 tests, zero failures. Log: `data/extension-node-regression.txt`.
- Browser: `node scripts/test_extension_bridge_ui.cjs` — seven checks pass in real local Chrome with intercepted HTML/API fixtures and simulated extension messaging: modern reload recovery, streaming refusal, duplicate-turn refusal, delayed composer/Send, idle and in-flight network recovery, scoped provider selection. No signed-in account is used.
- `git diff --check` passes.
- Independent review identified in-flight error classification and repeated Stop receipt loss. Both were reproduced with failing tests, fixed, and verified.

## Acceptance limits

Neither computer-use runtime could initialize in this session (`failed to write kernel assets`, OS error 3). No live ChatGPT smoke, extension installation/reload in the owner's profile, production-service restart or new video generation was performed. The owner still needs to reload 0.2.1 in ordinary Chrome and run Test chữ for live acceptance. Browser DOM changes and login/challenges can still require intervention; the one automatic fresh-tab retry retains its documented potential for a duplicate website question when the earlier send was uncertain.

This release stabilizes text transport. Flow and ChatGPT image providers retain their existing dedicated-browser requirements; choosing ComfyUI uses the local image path. Existing Flow/Gemini worktree changes were preserved; no StoryForge source was inspected.
