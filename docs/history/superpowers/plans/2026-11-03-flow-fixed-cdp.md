# Flow fixed CDP connection

The user confirmed manual Flow generation succeeds in the same VideoStudio profile with a fixed local CDP port and without `--enable-automation`. Integrate that exact launch configuration without navigator overrides or changes to image/task/checkpoint handling.

1. Add regression tests for a nonzero loopback CDP port, no automation flag, process/listener ownership, stale/mismatched endpoints, port conflicts and reconnect verification.
2. Default `BrowserConfig.debug_port` to 19223, configurable through `VS_CHROME_DEBUG_PORT`. Extend the existing Windows profile inspector with the declared CDP port and confirmation that its loopback listener belongs to the exact owned Chrome PID. Retain guarded legacy ephemeral-port discovery for a browser already running.
3. Discover fixed-port endpoints from the attested process instead of relying on `DevToolsActivePort`. Recheck PID, creation time, endpoint and listener after WebSocket connection, before sending CDP commands. Replace all production uses of `Browser.getBrowserCommandLine` with this attestation.
4. Check port availability before launching Chrome. Keep the existing idle-job and exact-profile stop guards. Update the isolated Windows fixture to use a separate nonzero port; verify connect, trusted input/click on about:blank and reconnect without generating media.
5. Run relevant browser/CDP/account tests, review the scoped changes, document configuration, and reload backend/daemon only while idle. Reuse the currently successful Chrome instance and its profile.

## Verification

- New guard tests observed failing before implementation, then passing after fixed-port launch and native ownership checks.
- **99 related tests passed**, including Chrome lifecycle/API, daemon, transport, pipeline, recovery and account handoff fixtures.
- Actual CDP fixture on the existing Chrome passed profile attestation, navigator.webdriver=false, trusted input/click on about:blank, owned-tab closure and reconnect. No generation requests were sent.
- Isolated Windows lifecycle fixture passed clean/debug/stop on a separate profile/nonzero port; the production Chrome process state was unchanged.
- One preexisting batch-route fixture expected the old call signature without reopen_project=False. Only its two assertions were aligned with the already-present route; no batch logic changed in this fix.
- Focused read-only review found no important issue in the new connection/ownership changes.
- Deployed with guarded backend/daemon restarts while idle; the successful Chrome instance was retained. Backend health returned OK, the production connector connected and attested its profile, and the reloaded backend reported debug_ready=true with zero active jobs. One existing Flow tab was observed; no generation request was sent.
- User acceptance on 2026-11-03: a complete 8-second video was created successfully through the tool. A longer video is the next acceptance check; it has not yet been reported complete. This acceptance is for the production browser/UI path, not the experimental direct-request FlowAPI path.
- Pre-push verification on 2026-11-03: all 568 Python tests and 121 JavaScript tests passed. Legacy ChatGPT-worker VM fixtures now isolate both ESM imports; the real-module lifecycle fixture supplies standard Chrome alarms/permissions/runtime event stubs. Production worker behavior was unchanged by these fixture updates. Cookie/HAR/profile runtime data remains ignored.
