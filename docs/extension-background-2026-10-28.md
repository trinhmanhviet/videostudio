# Background extension tabs, version 0.2.2

## Change

The existing ordinary-Chrome extension opens both the initial ChatGPT tab and its bounded retry with `active: false`. The extension does not activate windows/tabs or briefly switch focus and switch back. The owner already configured ChatGPT to remain active in Chrome; no browser performance settings, extra permissions, production jobs, or backend configuration were changed.

Reload **VideoStudio ChatGPT Bridge** in `chrome://extensions`, then reload the Studio page. The heartbeat keeps the 0.2.1 protocol identifier for compatibility with the already-running backend; this extension update requires no server restart. Login/challenge/unsupported-mode handling stays explicit and does not activate a tab automatically.

## Verification and boundaries

- Regression tests first demonstrated that both initial and retry paths used `active: true`; both pass after the change.
- `node --test extensions/videostudio-chatgpt/tests/*.test.mjs`: 28 tests pass.
- `node scripts/test_extension_bridge_ui.cjs`: existing seven intercepted Chromium UI checks pass.
- `node scripts/test_extension_background.cjs`: a separate fresh, headed Chrome with intercepted fixture pages verifies a truly hidden/unfocused ChatGPT-origin tab can run the shipped content script, submit once, receive and recover its reply, while the foreground input retains its focus and original value. The test's CDP connection only controls its own temporary browser, and the extension itself still uses ordinary Chrome extension APIs.
- Evidence: `data/extension-background/verification.json`. The successful run recorded hidden/unfocused before and after, zero visible transitions, one Send, and an unchanged focused foreground input.
- The first Playwright-based attempt was unsuitable because it emulates focus for pages; it was replaced with a direct test connection without focus emulation or timer-throttling overrides. The headed test requires desktop/socket access outside the Windows sandbox.
- No live signed-in ChatGPT request or extension reload in the owner's Chrome was performed: the computer-use tool still could not initialize. The short fixture run does not prove long-idle/throttling behavior or website-selector compatibility for every ChatGPT UI build.

Existing unrelated Flow/Gemini edits are preserved. No StoryForge source or video assets were read or changed.

## Owner acceptance

On 2026-10-28 the owner tested the background bridge in their ordinary Chrome and explicitly confirmed success in this chat. This is owner-reported live bridge acceptance; it does not establish a completed video generation run. The follow-up video connection and runtime switch are recorded in `extension-video-connection-2026-10-28.md`.
