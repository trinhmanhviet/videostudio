# Extension 0.3.1: Send after repair and recovery correlation

Owner requested fixing the two bugs reproduced during the review of commits through `5a50fec`.

- Before: a truncated insertion could be repaired to the correct full prompt but `button` was still null from the earlier mismatch loop. Fixture recorded a correct draft, enabled Send, zero clicks and `Send button unavailable`. Now repairs finish before acquiring the current Send button, including a replaced/re-enabled control. The composer is rechecked before one Send click.
- Before: content script accepted a collapsed user bubble's exact request marker while background compared its raw text to the full prompt and returned `foreign-turn`. Both now use the same matcher from `logical-text.js`, exported through `protocol.mjs` for the worker. Marker boundaries reject another ID sharing its prefix; incomplete/streaming/duplicate replies remain blocked by existing checks.

Regression evidence was recorded before each production fix. `node --test extensions/videostudio-chatgpt/tests/*.test.mjs tests/*.test.mjs` now passes 59 tests; log `data/bridge-send-recovery-node-tests.txt`. The real-Chromium intercepted bridge fixture includes repaired long input with replaced Send, collapsed user-turn recovery, prefix rejection and refusal to send a replaced composer. These checks use fake pages/runtime messaging and do not call the owner's ChatGPT account. Background and manager regression suites remain part of validation.

Update instructions: reload extension 0.3.1, then reload the existing connected Studio page. Press Start if needed after page reload. Compatible heartbeat build stays `videostudio-extension-0.3.0`. Existing receipts, attempt budgets, backend service and video assets were not reset. No production video, live prompt or synthetic heartbeat was initiated. The review's stale heartbeat must recover through the real connected page, not a fabricated server receipt.

True parallel video execution remains open in root `TODO.md`.
