# Visual Scene Grouping Implementation Plan

**Goal:** Automatically use one image for related narration while retaining independently timed captions.

**Architecture:** Version new plan checkpoints, normalize visual scenes before synthesis, and reuse the existing scene/utterance hierarchy. Keep legacy plans/caches unchanged. No additional LLM calls.

**Tech Stack:** Python, unittest, existing FFmpeg pipeline.

1. Add `tests/test_visual_scene_grouping.py`: cover new plan version, multi-sentence chapter scenes, preservation of canonical narration when optional line metadata disagrees, supplied-line grouping, legacy cached chapters, deterministic resume, and caption/image timeline integration. Run the file and confirm the new behaviors fail.
2. Add `videostudio/storyboard.py`: define shared semantic grouping instructions, normalize narration lines without losing words, and merge only explicitly matching contiguous supplied-line groups. Pass the existing `providers.split_caption_lines` as the splitter; its implementation and imports remain unchanged.
3. Modify `videostudio/providers.py`: mark newly produced plans; condition the short/chapter/provided prompts and normalization on that marker; persist the marker in new chapter plans; preserve the legacy branch for cached unversioned chapters. Preserve original supplied line manifests.
4. Run new tests and related multi-sentence, chapter, workflow, script-quality, reference and editor tests; correct regressions. Verify a local synthetic audio/image/caption timeline without live provider requests.
5. Update `TODO.md` and `README.md` with the behavior and deployment limitation. Review the scoped diff without changing unrelated pending edits.

## Verification

- Initial verification: 60 targeted script/caption/reference/render/editor-group tests and 19 editor API/extension-connection tests passed (79 total).
- The new grouping suite includes a real local FFmpeg render and full decode of a two-image, three-caption MP4. No live AI generation was performed.
- Focused review found that targeted factual repair could retain stale caption lines. Added a regression for short and long corrected narration, observed the original failure, and rebuilt caption lines while preserving the scene ID. Final verification includes this regression.
- Final combined run: **80 tests passed** in 16.5 seconds. Follow-up review confirmed the factual-repair issue resolved with no remaining important finding in the reviewed scope. The final backend was reloaded through the same idle-job guard and health returned OK.
- Backend reloaded through `scripts/start_extension.ps1 -RestartOwnServer` only after read-only SQLite inspection found no active video/image jobs. `/api/health` returned `status: ok`, `worker_enabled: true`, `text_transport: extension`.
- Still to observe in normal use: the semantic quality and actual image-count reduction on a newly generated AI video.
