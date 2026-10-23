# Connector integration checkpoint

## Changes actually made with owner approval

The EXISTING StoryForge extension was modified, not duplicated. Version is now 0.1.23. Only manifest.json and protocol.js changed for this integration: exact local origins localhost:8877 and 127.0.0.1:8877, existing production-route pattern, version bump. Existing uncommitted user changes were preserved. Before-change copies and hashes are in ignored data/connector-backup-20261024-010618. Trusted Start, receipts, delivery reconciliation, retries and tab ownership remain unchanged. No online deploy occurred.

VideoStudio now provides SQLite-backed immutable exchanges compatible with studio.js: scoped pending queue, response/version validation, accepted receipts, duplicate imports, scope isolation and restart request identity. Pipeline can request JSON through this transport (default chrome), not the failed proxy. Its UI creates a durable scope and production-route URL and labels the actual Create button for the existing trusted-click handler. It never manufactures a click or directly sends extension commands.

## Validation actually performed

- 84 existing connector fixture tests pass after origin change.
- 3 new exact-origin/port/frame/tab-isolation tests pass.
- 24 VideoStudio Python tests pass in 10.749 seconds, including scoped page and receipt HTTP API tests, immutable prompt recovery and conflicting import rejection.
- Inline UI JavaScript passes node --check.
- A real local server is reachable at http://127.0.0.1:8877; health and voice inventory checked over HTTP. Browser snapshot showed the three-input form, 25 preset voices, 3 usable clones, disabled archived clones and blocked production readiness. Existing preview matching was corrected by authoritative reference SHA-256; all 3 locked clones now have sample URLs.

## Not established

No real Chrome connector generation was performed. The owner must reload their installed existing extension to load the updated manifest. Browser testing used the built-in browser WITHOUT claiming it had the owner's extension or ChatGPT login. No synthetic trusted Start was used. Extension reload and live session are an outstanding human-presence dependency, not a successful integration test.

The existing connector requires the original Studio tab for ownership authorization. Durable server jobs and exchanges survive tab closure, but continued AI generation with that tab closed has NOT been achieved. This does not meet the original unattended/tab-close acceptance criterion. A deliberate further adaptation or supported server-side provider is still required, not removing the ownership safeguard.

Production remains locked. Natural-duration rewrite, live VieNeu/cache wiring, verified Stable Audio3 generation/usage conditions, research sourcing, scene semantic QA, robust GPU coordination and container execution remain outstanding. Do not advertise this checkpoint as the finished product.
