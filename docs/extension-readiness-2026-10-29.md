# Extension 0.3.3: cancelled panel cleanup and readiness repair

## Observed live evidence

The owner followed Reload/F5/Start but still saw two red preflight checks. The screenshot showed the connection Test failed with `Chat mode not confirmed`, and the panel retained cancelled videos. A read-only live API check confirmed a real heartbeat only 45.5 seconds old was rejected by the old 30-second window; the latest smoke was pending while an older accepted smoke remained stored. Both causes were real; resetting storage or writing a synthetic heartbeat/smoke would hide the failure.

## Corrections

- Content delivery selects Chat on its fresh owned conversation and verifies aria-pressed, aria-selected, aria-checked or active-tab state, then rechecks Chat at Send. It reacquires the composer after a mode switch and refuses nonempty/restored conversations.
- Uncertainty messages distinguish whether Send was attempted. Only the two exact historical pre-Send mode errors may use the existing bounded retry safely. Auth/challenge and after-Send uncertainty retain their protections; IDs and attempts are not reset.
- A service-worker alarm keeps the existing owner's root heartbeat alive while the Studio page timer is throttled. Pulse checks active state, real owner tab and exact production URL, uses a bounded fetch and the explicit extension client header. Stop and pulse writes share the same serial transition queue. Alarm is checked/recreated on startup per the [Chrome alarms API guidance](https://developer.chrome.com/docs/extensions/reference/api/alarms).
- Backend freshness and non-owner overwrite protection now use the same 90-second window. Only the known-scope informational heartbeat route accepts a valid chrome-extension origin with the explicit extension client header and loopback Host; other mutation origin protections remain unchanged.
- Authoritative `extension_status` separates heartbeat transport readiness from latest-smoke acceptance. Preflight now shows extension_transport and extension_smoke separately, with Vietnamese causes. An older successful smoke never silently replaces the pending latest test.
- Cancel-requested/cancelled videos and their stale video errors no longer render in the panel. Full internal session state is kept for cleanup/reconciliation and immutable receipts; assets are not deleted.

## Evidence

- 330 Python tests pass: `data/extension-033-python-tests.txt`.
- 70 Node tests pass: `data/extension-033-node-tests.txt`.
- Intercepted Chrome content/UI fixtures reproduce Work→Chat through both aria-pressed and aria-selected, skip an unnecessary switch when already selected, preserve the Send/marker fixes, and remove cancelled rows without stopping another video.
- A headed, genuinely hidden Chrome tab switches Work→Chat, sends once, receives/recovers its reply, and preserves foreground focus: `data/extension-background/verification.json`.
- `scripts/test_extension_connection_e2e.cjs` combines the actual content script, actual worker, real isolated API/SQLite and actual Pipeline preflight (media prerequisites are fixtures). Fresh smoke and a historical unsent mode-failed smoke both end with exact accepted receipts and every preflight check ready. Reports are under `data/connection-e2e/<run>/verification.json`.
- Independent review found no further concrete issue in the reviewed mode/filter/permission changes. These are fixture checks; direct personal-profile computer-use still fails to initialize, so no live account prompt or owner heartbeat was fabricated by the agent.

## Owner update

Backend must be restarted using the idle-only owned-server script to load the new status route/window. Then reload extension 0.3.3 and the connected Studio page. Press Start if not already active. A pre-Send mode-failed test can recover with the same pending request; login/challenges still need the owner. The manifest version is 0.3.3; the compatible heartbeat build remains `videostudio-extension-0.3.0`.

Actual parallel video generation remains open in root `TODO.md`.
