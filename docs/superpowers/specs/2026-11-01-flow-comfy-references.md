# Flow / Comfy fallback with real references

Owner-approved behavior: after a confirmed Flow refusal, generate two configured batches with Comfy, probe Flow with one scene, repeat while making progress. Preserve narration/music and existing images. Pending/unknown Flow requests are reconciled, never replaced speculatively.

Download only the unique loaded portrait displayed on the exact saved Character route. Attest task/job/entity/project; read the observed bitmap URL using the current page's normal same-origin image fetch, or fetch a public Google image CDN. No cookie extraction, no private generation endpoint or new portrait creation. Save PNG/hash and cache per job. Native download-button capture was rejected during live verification because it did not produce browser download events for Character exports.

Installed `TextEncodeQwenImage21` supports up to 16 references using `images.image_N`, with VAE and encoder latent output connected to sampling. Upload deterministic, hash-verified images through local Comfy API. Pad reference canvases without distorting identity. Store actual reference hashes and per-scene provider in checkpoints.

Hybrid routing state is persisted; completed Flow scenes are retained if another scene is refused. A terminal refusal needs scoped UI evidence, never inferred from timeout or missing tiles alone. Unknown receipt identity, auth and missing ref cases remain explicit recoverable errors. Each backend keeps its durable generation receipts.

Subtitle work is independent: bottom margin576 for Shorts/Reels, same timing/font and Flow crop.

Verification: offline fixtures for portrait capture/cache/identity, Qwen graph/image upload, partial refusal and two-batch/probe routing, cancellation and retry of mixed providers. No active job or services are changed during implementation; rollout only when idle. Live GPU test must be isolated from user video and an idle Comfy queue.
