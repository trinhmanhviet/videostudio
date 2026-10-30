# Float controls and Flow account continuation

Approved scope: move Chrome clean/debug/stop into the floating manager; provide self-service Flow account change while preserving the same video job and all downloaded images.

- [ ] Float: Chrome controls in a collapsible global section. Remove the static page panel. Per-Flow-video wizard: prepare, wait for safe pause and reconciliation, login with clean Chrome, reopen debug, continue. Poll state with clear messages. API errors must remain actionable; no job creation from wizard.
- [ ] Flow recovery service: persist phase/run/missing-scene metadata; validate/download accepted existing media and write per-scene checkpoints before account switch. Inspect unmatched old-project assets once using full prompt identity and preserve those which match pending scenes. Start a fresh Flow run namespace for remaining scenes after explicit continue. No hardcoded video IDs.
- [ ] Worker/API integration: cooperative `awaiting_flow_account` pause without cancellation; block worker queue during handoff; allow Chrome switches only after reconciliation. Expose GET /api/jobs/{id}/flow-account and POST prepare/continue. Keep cancel/retired-project guards and immutable task history. Route missing Flow tasks through active run ID; reuse old checkpoints.
- [ ] Verify isolated service/worker/UI fixtures and review. Deploy without cancelling current video; preserve receipts during a controlled transport restart only if needed. Do not initiate an actual account change on the running video for validation.

API status fields: phase (idle/pausing/reconciling/ready/running/error), message, cached_count, total, missing_count, can_prepare, can_continue. Prepare is idempotent; continue requires ready and debug mode and returns current state. Pausing/reconciling/ready block new worker work globally; only ready permits Chrome mode changes. Existing browser profile APIs remain unchanged.
