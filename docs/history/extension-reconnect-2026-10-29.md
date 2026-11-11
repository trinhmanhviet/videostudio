# Extension 0.3.2: reconnect instead of replacing the saved bridge

The screenshot's `Existing video sessions must be preserved; reconnect to their bridge` guard correctly protected pending work, but Start on the homepage always allocated a new scope. A page for another scope likewise attempted a different connection. The UI gave the owner no path back to the saved root.

Start now queries connection metadata from the worker, verifies the saved root through the existing local sessions API, and explicitly reconnects to that exact saved root. The worker moves controller ownership to the current Studio tab while keeping all session/tab/request state and retry counts. If the page path differs, it navigates to the saved bridge before sending a heartbeat. A first connection still creates its own root. A missing/changed saved root fails visibly instead of deleting pending sessions or silently creating a replacement.

No job cancellation, request resubmission, storage reset, live prompt or backend restart was performed. Fresh page hydration supplies the real heartbeat. Root `TODO.md` still tracks actual parallel video execution separately.

Red/green regression checks cover saved metadata discovery, preserving a pending child on reconnect, moving owner-tab binding, foreign/unsupported page rejection, saved-root mismatch, home/other-scope navigation without new scope allocation or foreign heartbeat, and first connection creation. Run the Node extension suite and `scripts/test_extension_manager_ui.cjs`; these use fixture state/pages, not the owner's Chrome profile.

Owner update: reload extension 0.3.2, reload Studio, click Start. No need to remove pending videos or clear extension storage.
