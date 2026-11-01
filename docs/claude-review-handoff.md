# Review handoff: VideoStudio ordinary-Chrome bridge

## Acceptance status: real bridge gate confirmed; full video still running

The later read-only live query confirmed a fresh heartbeat, latest smoke `8b89413f-ce05-482f-90e2-0e413190034f` accepted, and `preflight_ready:true` for bridge `d4f8200b-c895-4d58-8e01-7874d36a3d78`. The owner's real video `79d4d883-6cd2-4a4d-8ef1-9132af34f942`, child scope `94b8b75b-6517-4b8c-95d8-04e0b7e32704`, had real plan/research/script/speech checkpoints and was running images with no error. Evidence: `data/real-acceptance-status.json`.

This supersedes the earlier pending smoke observed during diagnosis. The agent could not initialize the personal-profile computer-use runtime (`failed to write kernel assets`, OS error 3); successful live activity came through the owner's normal browser workflow. No successful smoke or owner heartbeat was fabricated or imported from fixtures. Full video render/verification is not yet claimed.

An additional runtime-version diagnostic was implemented/tested in this final pass. Its backend hot deployment was intentionally refused by the idle-only script because the real video was active; the running server was preserved. Core 0.3.3 mode/heartbeat/gate fixes had already been deployed. Load the optional new diagnostic on the next idle restart; it is not needed to justify the observed accepted live smoke and real text-stage progress.

The working tree contains both owner/other-agent commits through `5a50fec` and earlier uncommitted bridge/Flow/Gemini work. Preserve them. Do not read `D:\Projects\storyforge` without the owner's request. Video output remains `E:\Videos`.

## Recent changes to inspect

- `extensions/videostudio-chatgpt/chatgpt.js`: verifies/selects the visible Chat control in an empty owned conversation, accepts pressed/selected/checked active semantics, reacquires the composer, checks Chat again before one Send; reports whether Send was attempted. Long-input repairs acquire the current Send button after repair.
- `logical-text.js` + `protocol.mjs` + `background.js`: common marker/text correlation with exact ID boundaries; independent persisted slots and retained legacy requests; no automatic focus; bounded known-unsent mode recovery preserves the request and retry budget.
- `background.js` + manifest: Chrome alarm heartbeat from the real active worker, owner tab URL/existence checks, serialized Stop/pulse, explicit client header. Adds only alarms permission. Reports actual manifest version as `runtime_version`.
- `studio.js`: cancelled/cancel-requested rows removed from visible manager without deleting immutable audit records; local cleanup still sees full server state. Reconnects the stored bridge instead of allocating a replacement, displays actual manifest version, reports it with page heartbeat.
- `videostudio/exchanges.py`, `providers.py`, `api.py`: 90-second freshness, separate heartbeat/latest-smoke checks, strict root/child ownership, latest pending smoke blocks readiness, read-only `/api/connector/bridges/{root}/status`. Status-only worker-origin exception requires explicit client header and loopback Host; other writes retain their origin guard.
- `connector_diagnostics.py`: bounded non-secret runtime version and error diagnostics. No credentials, prompts or raw browser state in status.

## Tests and their boundaries

- `node --test extensions/videostudio-chatgpt/tests/*.test.mjs tests/*.test.mjs`: 70 Node tests.
- `node scripts/test_extension_bridge_ui.cjs`: 14 intercepted real-Chromium checks.
- `node scripts/test_extension_manager_ui.cjs`: 21 intercepted manager checks.
- `node scripts/test_extension_background.cjs`: truly hidden headed Chrome Work→Chat/send/receive/recovery without foreground focus loss, fresh test profile only.
- `node scripts/test_extension_connection_e2e.cjs`: actual content script + actual worker + isolated FastAPI/SQLite/preflight; fixtures for website/model and media prerequisites. Fresh smoke and historical pre-Send mode failure both produce accepted receipts and all fixture gates ready. This is not live account acceptance.
- Python full regression before runtime-version-only diagnostic addition: 330 tests OK, log `data/extension-033-python-tests.txt`. New runtime diagnostic unit passes separately; rerun affected diagnostics/readiness or full suite as appropriate.

Tests requiring Windows sockets/headed desktop ran outside the sandbox using isolated TMP/VS_DATABASE/voice fixture directories. No new production video was generated.

## Live completion criteria and current evidence

1. Runtime version is now instrumented in producer code; its backend diagnostic deployment is deferred until idle. This field was not available in the current running server, so direct label verification is not claimed.
2. VERIFIED: a new real exact correlated smoke response was imported through the normal receipt path. No DB response/heartbeat was set manually and no older smoke bypassed the latest pending one.
3. VERIFIED: read-only status and `/api/preflight?scope=<root>` reported `ready:true` for the same real bridge.
4. VERIFIED FOR TEXT STAGES: the owner started a video in its own child scope; plan/research/script/speech checkpoints completed and images were running without error. Cancelled-row cleanup passed UI fixtures; direct personal-profile visual confirmation is not claimed.
5. OPEN: full output video completion and owner content/quality acceptance after image/music/render stages finish.

Actual parallel video execution remains explicitly open in root `TODO.md`; current worker/GPU execution is serial.
