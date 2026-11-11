# Recovery release 0.3.4

Owner approved using Comfy `/free` and restarting through the existing verified SageAttention batch if it crashes. Launcher remains `D:\1_SD_and_workflow\ComfyUI-Easy-Install\ComfyUI-Easy-Install\Start ComfyUI SageAttention.bat`, pinned SHA256 `590a95b06f12165dc60de6aaf8119a9b7ee8a5d246a56d034c8074a6f1cf64b6`.

Shipped: actual idle-only Comfy unload, physical VRAM recheck and bounded absent-service recovery; valid downloaded assets survive cleanup failure. No duplicate prompt submission from missing old receipts. Strict per-scene shared-service behavior retained. Initial-absent Comfy automatic start remains a TODO; it is not needed for the currently healthy service.

Failed job cards now update on state changes and always expose `Tiếp tục từ bước <stage>` independent of diagnostics. Retry queues the same job and preserves prior checkpoints. Editor shows export availability/missing stages, disables incomplete export, and offers recovery of the original job. Server still rejects missing prerequisites before child allocation.

Prompt changes: paragraph extraction uses DOM text rather than CSS-derived innerText, preserving URLs/blank paragraphs/Unicode; chunking no longer splits surrogate pairs. Native Chromium tests replay the complete recorded 6134-character prompt. Exact observed +7 source is not confirmed; seven URL occurrences and first URL offset1591 match the incident. Unknown added characters remain blocked. A scoped local diagnostic API now saves bounded codepoint/DOM evidence for future real failures, without full prompts or checkpoint changes.

Verified: Python360 tests, Node71 tests,8 composer cases,14 bridge UI checks, mobile/desktop recovery controls, editor layout/generation regressions. Independent review found no confirmed blocker in the recovery/export paths.

Backend was updated idle-only (PID32920). Original job `79d4d883-6cd2-4a4d-8ef1-9132af34f942` was queued again at music using its normal retry API, after checking an empty Comfy queue and all10 existing asset hashes. Existing plan/research/script/speech/images/subtitles retained. Baseline: `data/recovery-79d4d883-before.json`. Completion/render acceptance is separate from this deployment record.

Owner: F5 Studio for the new recovery controls; reload extension0.3.4 for future text-generation tests. No new video job is required to continue the original music/render path. True parallel video execution remains open in TODO.md.
