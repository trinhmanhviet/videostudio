# Initial implementation audit

Evidence from local code/runtime inspected during this implementation. This is not an end-to-end acceptance report.

## Project isolation

- `D:\Projects\videostudio` was empty and not a Git repository at inspection.
- `D:\Projects\storyforge` contains uncommitted user work in web and extension files. Treat the entire reference project as read-only. No copying `.env*`, credentials, DB or model caches into the new repository.
- Docker context was `desktop-linux`; existing StoryForge API/web/production-worker/Postgres/Redis/MinIO and remote/tunnel containers were stopped. Do not restart those services or publish remotely as a side effect of developing this product.

## Manual gates that cannot be silently reused

- `apps/api/app/services/preproduction.py` transitions into `awaiting_chatgpt`.
- `apps/api/app/db/models/production.py` contains `awaiting_image_review` and approved snapshots.
- `apps/api/app/api/production.py` exposes image approval and run approval endpoints.
- `extensions/chatgpt-web/studio.js` checks `event.isTrusted` before start/restart and scopes exchanges by project/run. It reconciles receipts before another send and preserves uncertain delivery state. Simulated clicks or a second connector would violate these safeguards.
- `docs/video-creator-local-design.md` describes a manual music review/export flow and says its Stable Audio workflow had not been live-tested. This document is historical technical context, not proof of functionality.

## Voice preservation

- `apps/api/app/data/voice-presets.json` is canonical preset metadata. Clone IDs/references live in StoryForge durable assets/database, not this preset JSON.
- `Voices/Sources`, `Voices/Samples`, `Voices/Previews` contain existing media. They must remain unchanged.
- Presence of sample WAV files does not identify all confirmed clone voices. A successful import must preserve authoritative clone IDs/names/reference hashes and must fail readiness when the requested complete library cannot be verified. Never silently offer just presets as the full library.

## Media runtime

- ComfyUI responds at host `http://127.0.0.1:8188`. Its system_stats reports ComfyUI 0.37.0, embedded Python 3.12.10 and RTX 3090 Ti 24GB.
- Snapshot free VRAM was approximately 4GB. This is not sufficient evidence of safe image model loading; do not unload models owned by another application.
- `/object_info` was opened read-only and lists Qwen Image 2.1 encoder, UNETLoader, audio conditioning/latent/decoder/save nodes. Node presence alone does not prove Stable Audio 3 model identity, workflow correctness, installed weights or usage rights.
- StoryForge `providers/images/comfy.py` hardcodes Qwen 2.1 workflow and calls global `/free` before rendering. Do not copy the global unload behavior: an empty queue does not prove all resident models belong to VideoStudio.
- StoryForge VieNeu is loaded in a native media worker using pinned environment/cache. It is not automatically an HTTP service at port 7860.
- FFmpeg and FFprobe are installed on Windows. That does not establish their availability inside a new Linux container.

## Acceptance boundaries

An automated run requires a supported, explicitly configured unattended language backend; an authoritative imported voice library; a tested local VieNeu path; verified Comfy image workflow; verified Stable Audio 3 local workflow with its license conditions; persistent writable output volumes and container probes. Until those pass, fail preflight before accepting production jobs. Synthetic fixtures can validate orchestration/render mechanics but are never evidence of AI generation or a completed product.
