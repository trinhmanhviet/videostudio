# Existing Chrome connector inspection

Read-only inspection followed the owner's request to assess the existing connector, not replace it with ChatGPT2API.

## Verified source constraints

- `extensions/chatgpt-web/manifest.json` permits local Studio only on localhost:3000 / 127.0.0.1:3000 and specified HTTPS origins. The production content script matches `/story-video/projects/*/production*` only.
- `protocol.js` enforces exact allowed origins and scope. VideoStudio's intended local port 8877 is not authorized.
- `studio.js` accepts start/restart only from a trusted click on its start/restart control within its scoped panel. It polls exchanges through StoryForge's same-origin API paths.
- `background.js` independently verifies the original Studio tab, project/run scope and delivery authorization before sending; receipts correlate the immutable user turn. These checks must remain.

## Tests actually executed

`node --test extensions/chatgpt-web/tests/bridge.test.js extensions/chatgpt-web/tests/background.test.js extensions/chatgpt-web/tests/studio.test.js`

84 tests passed, 0 failed, in 1539.8887ms. This validates fixture-based connector mechanics, not a live logged-in Chrome session or VideoStudio integration.

## Integration gap

Existing connector is not plug-compatible with VideoStudio. Reusing it requires a deliberate minimal extension change for the exact local VideoStudio origin/route, a compatible durable exchange API in VideoStudio and wiring a REAL initial Create video click to the existing start authorization. No synthesized click, broad wildcard origin, parallel Chrome connector or disabled receipt check is acceptable. The current model uses a live Studio tab for ownership checks, so closing that tab does not establish continued unattended generation; worker-side recovery must preserve checkpoint and stop honestly or reattach without resend.

StoryForge contains uncommitted user changes to these extension files. They have not been modified by this implementation. Owner approval of editing this existing shared extension is required before changing its behavior. No evidence yet proves this approach meets tab-close acceptance. Product remains incomplete.
