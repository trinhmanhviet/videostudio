# Quick / Careful modes and per-scene visual revisions

## User workflow
New videos default to **Nhanh**. This runs normal generation and technical verification, with no mandatory image reviewer. **Kiểm kỹ** currently means explicit human review: narration, images, captions and music are generated; before render the worker enters `awaiting_visual_review`. It releases its lease and waiting consumes no render retry attempt.

Open **Xem / sửa ảnh từng cảnh** on a completed, failed-after-images, or awaiting-review job. Change Quick/Careful in the editor without discarding image edits or approvals. The original request/idempotency receipt remains unchanged; effective editor mode is stored separately. A completed Quick video can be opened as Careful, a few images replaced, and the remaining current images explicitly retained. Changing mode does not regenerate content or retroactively certify the original MP4.

Each scene shows its immutable narration/timing, current image, audio preview, framing choice, user approval, and image history. Upload a still PNG/JPEG/WebP then click **Dùng ảnh này**. Upload is an explicit user selection, not AI certification. History supports restoring the original or an earlier uploaded version. Careful export requires all images approved, or the user explicitly checking the keep-current-images confirmation. Quick export does not impose that review gate. Switching modes preserves these choices.

## Original media and export boundaries
Edits are immutable files under `data/scene-edits/<source-job>/`, never overwrites of source image checkpoints. Export freezes the current editor version into a NEW job/output directory, beginning at render. It copies the existing speech, subtitle and music checkpoints, preserving narration bytes, scene order/timing and selected voice. Valid unchanged visual clips are copied with their cache receipts; changed visuals are re-rendered. Subtitle files are copied byte-for-byte into the new renderer cwd.

For an already verified completed video, the new MP4 **stream-copies its existing audio track**, avoiding mixing/re-encoding changes. For a video that has not yet been rendered, it uses the normal soundtrack composition from the unchanged speech/music assets. Final MP4 video encoding may still cover the full duration. There is no claim that changing one image makes whole-file export instantaneous.

The original job/video remains intact. Awaiting-review originals can have multiple export revisions; they do not automatically resume or become completed merely because a child revision was exported. New revisions appear as new video cards in the same project. Waiting jobs can be cancelled. Files shared with a source revision are still hash-attested; deleting source media is not supported.

## Safety and concurrency
- Existing origin protection is enforced for all mutating editor routes. Existing Cloudflare Access protection remains unchanged.
- Raw bytes only, max 20 MB, still PNG/JPEG/WebP, dimensions 32..8192 with max 20 million pixels. No SVG, remote URL or client-supplied filesystem path. Decoded EXIF orientation is applied; output is RGB PNG at 1080x1920, either center-cover or contained on black, without stretching.
- Job+scene+edit scoping prevents another scene's edit IDs from being read. Image/audio reads require checkpoint or edit hash matches.
- Optimistic editor version plus SQLite write transaction rejects stale mutations/exports. Idempotency keys are bound to source/version/confirmation; repeated export retries return the same child. Subsequent edits cannot change a previously frozen export.
- User approvals bind image hash and timeline fingerprint; changed selections do not inherit approval for different pixels. Export snapshot provenance is stored in DB and checked at render/verify.
- UI does not permit modifying a running job. Wait until generation reaches the review boundary or completes. Mode switching/editing an already settled video is supported.
- Automated `VS_VISUAL_QA=required` remains a separate experimental protocol. Existing pinned required policies cannot downgrade. Explicit user-facing quality modes use technical/manual checking, not that unconnected transport. Human selection does not need or forge an automated review signature.

## Verification performed
- Unit/API tests exercise modes, switching with edits, upload normalization/rejection, restore, stale writes/approvals/export, immutable snapshots, explicit bulk retention, cross-origin rejection, pending review/retry/lease behavior and restart persistence.
- Isolated browser smoke at port 8881 used existing local media to render an 8-second source; through the UI it switched Quick/Careful repeatedly, uploaded a replacement, blocked unapproved Careful export and exported a new revision after explicit retention confirmation.
- Final smoke verification compared both 8-second durations, identical speech/subtitles/music checkpoints, unchanged scene durations and original MP4 hash, reuse of the unchanged scene clip and **identical SHA-256 of decoded final audio** after stream-copying the original track.
- No full armor-video regeneration, model download, ChatGPT request, TTS or GPU image generation was performed.

Reproduce isolated smoke (not production):

```powershell
C:\Python312\python.exe -m scripts.scene_editor_smoke --serve --port 8881
# After the browser-driven edit/export completes:
C:\Python312\python.exe -m scripts.verify_scene_editor_smoke
```

Local evidence is under `data/editor-smoke/<run>/smoke-verification.json`. This is a mechanics/continuity test, not a claim that replacement fixture imagery matches the story or that a VLM detects historical errors. Autonomous multimodal review remains unavailable/unvalidated.
