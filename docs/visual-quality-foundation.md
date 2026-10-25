# Visual quality foundation (not autonomous visual acceptance)

## What is delivered
- `visual_quality.py`: typed project/scene contracts, stable content-based fallback IDs, conservative prompt-conflict lint, positive/negative compilation, artifact-bound review receipts, release validation.
- `VS_VISUAL_QA=legacy` (default): original generation behavior; outputs explicitly say visual quality `not_checked` and scope `technical_only`.
- `VS_VISUAL_QA=required`: separate, opt-in path in images/render/verify. A persisted `visual-policy.json` and checkpoint flag pin required mode, even after restart or environment downgrade. Invalid modes/policy/contracts stop before GPU work.
- No new model, API, image download/upload, inference request, or production restart performed by this change.
- Existing armor project, 196 source images, narration, soundtrack and MP4 remain immutable. The audit is outside that directory.

## Current hard blocker to enabling required mode
VideoStudio's CDP transport currently sends text only. An authenticated model account is NOT a verified image-upload/review transport. This patch does not pretend otherwise. Missing reviewer returns `needs_review` and does not become a pass. Required mode refuses a GPU submission if there is no reviewer and no existing valid signed receipt for every planned artifact.

A future supported adapter is an explicitly registered `pipeline.visual_reviewer(image_path, contract, check)` callback. It must actually inspect the supplied image, not just its prompt. It returns:

```json
{
  "status": "pass",
  "reviewer": "configured-model-and-policy-version",
  "observations": ["Concrete visible evidence relevant to must_show"],
  "issues": [],
  "uncertain": false
}
```

Other statuses: `fail`, `needs_review`. Empty observations, malformed output, adapter failure, uncertainty, conflicting pass+issues, or mutation of the image during review cannot approve it. Cancellation propagates. This is a transport INTERFACE, not a delivered autonomous reviewer or a usable manual-review UI.

Receipts are signed with HMAC using an operator-provisioned local `VS_VISUAL_REVIEW_SECRET` (>=32 chars). No secret was configured during this implementation. Missing/changed key invalidates approvals. A reviewer response is signed by the local pipeline, never accepted as arbitrary uploaded JSON. Signature protects against accidental/offline receipt edits, not a hostile local user/process that can read the signing key, modify code or contract files. Reviewer calibration/accuracy is explicitly unvalidated.

## Contract sidecar
For newly opted-in jobs, `visual-contracts.json` sits in that job directory. The offline command emits `contracts-draft.json` elsewhere. It is intentionally invalid until scene intent and requirements are specified; do not rename the draft and expect semantic acceptance.

```json
{
  "schema_version": 1,
  "job_id": "exact job UUID",
  "project": {"schema_version": 1, "style": "natural material textures", "identities": []},
  "scenes": [{
    "scene_id": "stable-safe-id",
    "narration_sha256": "hash returned by text_hash for this final utterance",
    "intent": "reconstruction",
    "context": {"era": "scene-specific", "region": "scene-specific", "setting": "scene-specific"},
    "must_show": ["concrete subject/material/action"],
    "avoid": ["objects prohibited ONLY in this scene"],
    "references": [],
    "separate_subjects": false
  }]
}
```

Intent enum: reconstruction, contemporary, museum, comparison, diagram, metaphor, fiction. Comparison requires `separate_subjects=true`, compiles a separation instruction. It does not globally prohibit contemporary objects. Context supports era/region/setting/species/mechanism/world; unused fields can be omitted. References use `{path,sha256,note}` pointing to already reviewed source material; changing a file invalidates compilation/release. Reference hashes provide provenance, NOT image-reference conditioning: the current image graph is still text-to-image.

Unknown historical/scientific details should remain unresolved until sourced. Neither a generated contract nor its schema validity proves truth. No new scene planner or historical fact retrieval was implemented here.

## Cache and revision handling
`conditioning_key` includes compiled prompts, full scene contract/references, schema version and actual generated graph (seed, node/model filenames, parameters). New images use a namespace containing scene ID+conditioning key and never overwrite legacy `images-NNNN.png`. Changing a contract, prompt, reference or graph produces another artifact. Release rechecks current image hash, receipt signature, full contract, final utterance binding, ordering and graph key.

LIMIT: graph filenames are NOT actual model weight/version hashes. Runtime custom-node revisions and renamed-in-place model weights are not auto-attested in this slice; a production image reviewer integration must add trusted model/node revision hashes before claiming full runtime reproducibility. No CFG settings were changed and negative conditioning effectiveness has not been established.

Stable IDs: explicit `scene_id` is retained; missing IDs fall back to normalized narration hash, independent of reorder and visual-prompt changes. Duplicate narration without explicit IDs is rejected rather than silently mapping wrong. Unchanged utterances retain identity through cuts. Upstream propagation for substantively rewritten narration, entity tracking and chapter mappings is NOT solved by this fallback and remains future work.

Visual revisions use new image/clip paths, leaving narration cached. Existing completed jobs are not invalidated or automatically regenerated. No auto-retry/repair loop is turned on: failed/uncertain review stops safely; adding repair generation needs its own bounded budget and end-to-end tests.

## Offline audit

```powershell
C:\Python312\python.exe -m videostudio.visual_audit --job-dir "E:\Videos\<existing-project>" --out "data\visual-audits\<unique-audit>" --labels tests\fixtures\visual-regression.json
```

Command uses read-only source access; refuses output inside the source directory and refuses overwriting an existing report. Emits inventory+contract drafts, no model/GPU calls. Screenshot labels are bound to screenshot hashes, NOT silently applied as a completed review of original PNG pixels. `not_checked` is deliberate.

Current local inventory: `data/visual-audits/f9d386c3-foundation/audit.json`, 196 scenes. Seven labels: five user-reported failures inspected with native vision, one narrow forge-ending control, one alternative contemporary intent using the same PPE pixels. The latter tests "modernity alone is not an error"; it is not general scene/historical approval. Labels do NOT represent model predictions or detector accuracy.

## Next separate milestones (not shipped / not enabled)
1. Verify a supported non-paid image-review path under the user's accounts, including image upload privacy, authentication handling and request receipts. Do not invent private API calls or download a vision model silently.
2. Ground and persist scene contracts before image generation, propagate IDs through all script/duration transformations.
3. Add actual model/node artifact revisions to cache identities; calibrate reviewer pass/fail/uncertain against user labels.
4. Obtain a bounded pilot generation budget. Include multi-era history, intentional modern comparisons, science diagrams, wildlife, contemporary scenes and fiction. Measure critical defect rate, false approvals vs human labels, retries, time and cost.
5. Only then enable required mode for new jobs and plan repair of original video into a NEW revision. Never overwrite the original MP4.
