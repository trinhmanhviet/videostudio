# VideoStudio local - implementation in progress

**Not production-ready. No idea-to-video AI end-to-end acceptance has passed.**

The repository contains a working durable-job backend, HTTP API and connected three-input frontend. Preflight deliberately blocks production job creation. This is an engineering checkpoint, not delivery of the requested finished product.

## Run the local inspection UI

From this directory, with the existing Python environment providing FastAPI, uvicorn, httpx and Pillow:

```powershell
python -m uvicorn videostudio.api:app --host 127.0.0.1 --port 8877
```

Open http://127.0.0.1:8877. This does not restart StoryForge, use the Chrome extension or contact paid services. Preflight reports unmet conditions. No credentials are copied automatically.

## Tests actually rerun by the parent engineer

`python -m unittest discover -s tests -v`: 14 tests passed, 7.046 seconds.

- SQLite job creation, idempotent requests, conflicting payloads, output collision isolation.
- Checkpoint continuation, finite persisted retry budget, worker lease exclusion, queued/in-stage cancellation and corrupted asset rejection.
- API checks, blocked preflight rejecting job before allocation, same-origin mutation guards and frontend response.
- CPU FFmpeg integration with synthetic image and sine-wave audio fixtures; real encoding, stream probing and duration assertion.

That FFmpeg test is NOT speech synthesis, music generation, model output, visual/semantic review, GPU integration or a completed user video. Browser click/reload acceptance and container execution were not performed.

## Unfinished requirements and blockers

- The existing Chrome connector now exchanges a real correlated JSON smoke response with VideoStudio after the owner's real click. No parallel extension or fake trusted gesture is used. Its dependency on the Studio tab still blocks the original fully unattended/tab-close acceptance. Failed ChatGPT2API is not the default transport.
- VieNeu now uses the existing StoryForge CPU/ONNX Python and offline cache. A live manhviet clone test produced 4.32s of PCM audio, full decode/finite samples/non-silence passed. This does not yet prove full narration semantic completeness or every voice.
- Follow-up: authoritative read-only DB import now preserves all 25 presets and all 3 locked user clones with matching reference hashes, plus 3 archived clones retained but disabled. Existing StoryForge voices are untouched. Local export is ignored by Git. See `docs/integration-followup.md` for owner-authorized service starts and evidence.
- Research currently retrieves local `.txt` sources only, not automatic web discovery or claim verification.
- Updated: storyboard schema now requests short per-scene utterances and separate visual prompts. Speech code measures independent utterances, caches them by voice/text hash, and captions use measured utterance intervals with Unicode preservation, overlap and line-width checks. Images have per-scene receipts/checkpoints. The full provider chain has not been exercised end-to-end. Bounded measured-duration script rewriting is implemented with cached revisions and two passing fixture tests, but not yet accepted with live generated scripts. Semantic/continuity checks remain incomplete.
- Renderer now encodes 1080x1920/30fps, builds cached pan/zoom scene clips, preserves natural speech speed (no atempo), permits a bounded final visual hold, and mixes with music fade, sidechain ducking and limiter. A two-scene CPU fixture render passes. Music loop crossfade and live speech/music QA remain unfinished. Do not use fixture output as AI product acceptance.
- Comfy model/node availability is verified read-only, not live graph execution. Stable Audio3 blueprint remains unverified; no commercial rights claim is made. No GPU work has run.
- Worker lease serializes this tool's work only; cross-application GPU ownership/VRAM coordination remains unfinished. No global unload, interrupt or kill is used.
- Docker packaging exists but has not been built/tested. It defaults to worker disabled and is not a ready containerized generation runtime. Container host routing and persistent volume/permissions remain unverified.
- Production readiness is explicitly hard-blocked until these engineering requirements and live end-to-end tests pass. Setting credentials alone does not remove that gate.

See `docs/initial-audit.md` and `docs/preflight-observed.json` for inspected evidence. Existing videos, models, StoryForge code and online deployment were not modified.
