# Multiple video sessions implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development. Work in the existing checkout and preserve all pre-existing Flow/Gemini and bridge work. No commits or personal-profile automation needed.

**Goal:** Let the owner queue multiple videos through one background ChatGPT bridge and manage them without losing previous session receipts.

**Architecture:** Parent bridge root with persisted child connector scopes, isolated extension request slots, one floating controller. Existing worker remains sequential. Contract: `docs/superpowers/specs/2026-10-28-multi-video-bridge-design.md`.

**Tech Stack:** SQLite/Python/FastAPI, Chrome MV3, JavaScript, Python unittest, Node test runner, intercepted real Chrome fixtures.

- [ ] Backend: reproduce second-job rejection; test repeated allocations, scope ownership, idempotency, old-failed-job coexistence, pending filtering, scoped cancellation and parent acceptance. Implement membership/atomic job scope creation and three bridge endpoints. Run focused API tests with isolated temp DB and voice root.
- [ ] Extension worker: test legacy migration, independent slots, exact callback binding, failed-slot coexistence, scoped cancellation/opening and background creation. Extend persisted state/routing without relaxing immutable receipts or retry limits. Keep existing public legacy helpers where possible. Run Node tests.
- [ ] Floating manager: build against approved API/worker snapshot contract; test expanded/collapsed persistence, mobile overflow, correct video actions, cancellation isolation and recovery after reload. Keep existing bridge core behavior while polling bridge-wide sessions/pending and per-scope slots.
- [ ] Integrate: exercise multiple queued videos through actual worker/exchange API with fixture JSON; run Python regression + Node regression + intercepted UI + hidden-tab renderer check. Independent specification and code review; fix actionable issues and rerun affected tests.
- [ ] Delivery: record results, keep TODO for true parallel video execution open, idle-only restart owned VideoStudio API in extension mode, verify root/child preflight and no unexpected job creation; instruct owner to reload updated extension/Studio.
