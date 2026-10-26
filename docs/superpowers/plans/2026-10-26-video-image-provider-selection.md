# Video image-provider selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow each new VideoStudio video job to choose Flow, ChatGPT, or Comfy for all initial scene images, defaulting to Flow, and make Flow the default for per-scene rerenders.

**Architecture:** Store a validated `image_provider` in each new job request and route the existing serial `Pipeline.images` loop through one provider adapter per scene. Flow uses the existing dedicated CDP browser, one Flow tab, and one durable Flow project per VideoStudio job; every scene still requires the visible 0-credit gate and 2K download. Legacy jobs without the field continue using Comfy, while the Scene Editor keeps rerenders candidate-only.

**Tech Stack:** Python 3.12, FastAPI, SQLite, existing VideoStudio Worker/Pipeline, dedicated Chrome CDP, static HTML/JavaScript, unittest, Playwright UI regression.

---

## File map

- Modify `D:\Projects\videostudio\videostudio\core.py`: validate and persist the `image_provider` request field.
- Modify `D:\Projects\videostudio\static\index.html`: add the initial video form selector, serialize the selected provider, and bump the Scene Editor script cache key.
- Modify `D:\Projects\videostudio\videostudio\providers.py`: route each initial scene image through Flow, ChatGPT, or Comfy; preserve Comfy fallback for legacy jobs and strict visual-QA gates.
- Modify `D:\Projects\videostudio\videostudio\cdp_flow.py`: persist one Flow project per video job and safely correlate sequential outputs within that project.
- Modify `D:\Projects\videostudio\static\scene-editor.js`: default first-use rerender selection to Flow and keep all three providers selectable.
- Add/modify tests in `D:\Projects\videostudio\tests\test_backend.py`, `D:\Projects\videostudio\tests\test_cdp_flow.py`, `D:\Projects\videostudio\tests\test_image_provider_routing.py`, and `D:\Projects\videostudio\scripts\test_scene_generation_ui.cjs`.
- No changes to Comfy graphs, account auth, browser profiles, or private Flow endpoints.

## Task 1: Add a validated provider field with legacy-compatible defaults

**Files:**
- Modify `videostudio/core.py`
- Test `tests/test_backend.py`

- [ ] **Step 1: Add failing request tests**

Add to `DurableTests`:

```python
    def test_image_provider_defaults_to_flow_and_validates_enum(self):
        self.assertEqual(validate_request(REQUEST)['image_provider'], 'flow')
        for provider in ('flow', 'chatgpt', 'comfy'):
            self.assertEqual(validate_request({**REQUEST, 'image_provider': provider})['image_provider'], provider)
        for provider in ('unknown', '', None, 2):
            with self.assertRaises(ValueError):
                validate_request({**REQUEST, 'image_provider': provider})
```

Run: `C:\Python312\python.exe -m unittest discover -s tests -p 'test_backend.py' -q`
Expected: FAIL because `image_provider` is currently rejected/omitted.

- [ ] **Step 2: Implement minimal schema validation**

In `validate_request`, add `image_provider` to `allowed`, then set:

```python
    provider=data.get('image_provider','flow')
    if provider not in ('flow','chatgpt','comfy'):
        raise ValueError('image_provider must be flow, chatgpt, or comfy')
    res['image_provider']=provider
```

Do not rewrite old rows in SQLite. `Pipeline.images` will separately interpret a missing field on already-persisted jobs as legacy Comfy.

- [ ] **Step 3: Run the focused backend tests**

Run: `C:\Python312\python.exe -m unittest discover -s tests -p 'test_backend.py' -q`
Expected: PASS, including idempotency and old-request validation.

- [ ] **Step 4: Commit**

```powershell
git add videostudio/core.py tests/test_backend.py
git commit -m "feat: persist initial image provider in video jobs"
```

## Task 2: Add the initial-job selector and submit the chosen provider

**Files:**
- Modify `static/index.html`
- Test `scripts/test_scene_generation_ui.cjs` or add `scripts/test_initial_image_provider_ui.cjs`

- [ ] **Step 1: Write a failing UI regression**

In the isolated form test, assert that `#imageProvider` has options `flow`, `chatgpt`, and `comfy`, starts at `flow`, and that changing it to `comfy` makes the `/api/jobs` POST payload contain `image_provider: 'comfy'`. Also assert that leaving it unchanged submits `flow`.

Run: `node scripts/test_initial_image_provider_ui.cjs`
Expected: FAIL because the initial job form currently has no image-provider control.

- [ ] **Step 2: Add the form control and payload field**

Insert near the idea/voice fields in the initial video form:

```html
<label for="imageProvider">Nguồn tạo ảnh cảnh</label>
<select id="imageProvider" required>
  <option value="flow" selected>Google Flow</option>
  <option value="chatgpt">ChatGPT</option>
  <option value="comfy">ComfyUI · Qwen Image 2.1</option>
</select>
<small id="imageProviderNote">Flow chỉ gửi khi xác nhận 0 tín dụng; dùng một project riêng cho video.</small>
```

Add `image_provider: $('#imageProvider').value` to the create-job payload. Preserve the selected value in the idempotency identity because the full payload already determines the identity.

- [ ] **Step 3: Add a visible zero-credit note for Flow**

Update the note on selector change so the Flow choice states its 0-credit stop condition, ChatGPT uses the existing dedicated browser, and Comfy uses the existing Qwen workflow. The backend remains authoritative for whether the Flow call may submit.

- [ ] **Step 4: Run the UI regression and syntax check**

Run: `node scripts/test_initial_image_provider_ui.cjs`
Expected: PASS for default Flow and explicit ChatGPT/Comfy selection.

Run: `node --check` is not available for HTML inline scripts directly; the Playwright test must load the actual `static/index.html` and exercise its submit handler.

- [ ] **Step 5: Commit**

```powershell
git add static/index.html scripts/test_initial_image_provider_ui.cjs
git commit -m "feat(ui): select image provider for new video jobs"
```

## Task 3: Make Flow project reuse job-scoped and correlate multiple scene outputs

**Files:**
- Modify `videostudio/cdp_flow.py`
- Test `tests/test_cdp_flow.py`

- [ ] **Step 1: Add failing project-registry tests**

Add tests showing that the first task for a `job_id` clicks **Dự án mới** once and atomically records its Flow project URL; the second task for the same `job_id` reuses the saved URL and does not create another project. A distinct `job_id` creates a distinct project. Multiple Flow tabs still fail closed.

Run: `C:\Python312\python.exe -m unittest discover -s tests -p 'test_cdp_flow.py' -q`
Expected: FAIL because current Flow receipts create a new project per task and do not maintain a job registry.

- [ ] **Step 2: Implement an atomic job-to-project registry**

Add helpers in `FlowImages` that validate `job_id` as UUID and store `data/flow-images/projects/<job_id>.json` using temp-file plus replace. The registry stores only `job_id`, Flow project URL, and creation time. New scene receipts copy the URL from this registry; existing task receipts remain authoritative for resume.

In `_ensure_project`, use the registry when the current request has no task receipt. Navigate only within the existing single Flow tab and only when there is no draft or active generation. Never close any Flow tab or alter the existing demo project's content.

- [ ] **Step 3: Correlate a single new card within the shared project**

Before submit, persist the baseline set of Flow result-card identities and the prompt hash. After submit, require exactly one new completed card beyond the baseline. If Flow exposes reliable prompt text for that card, verify its normalized text; otherwise rely on the one-tab, serialized job/scene identity and require exactly one newly-added result. If the count grows by more than one or identity is ambiguous, stop as `uncertain`; do not pick an arbitrary image or submit again.

On recovery, compare the same project URL, prompt hash, baseline, and new card identity before continuing to the existing 2K visible-download flow. Reuse a validated downloaded file from the same task receipt without re-generating.

- [ ] **Step 4: Run focused Flow safety tests**

Run: `C:\Python312\python.exe -m unittest discover -s tests -p 'test_cdp_flow.py' -q`
Expected: PASS for registry reuse, one-tab refusal, 0-credit gate, task correlation, 2K frame/GUID validation, and no duplicate submit.

- [ ] **Step 5: Commit**

```powershell
git add videostudio/cdp_flow.py tests/test_cdp_flow.py
git commit -m "feat(flow): reuse one project per video job"
```

## Task 4: Route bulk initial scene images by the persisted job provider

**Files:**
- Modify `videostudio/providers.py`
- Add `tests/test_image_provider_routing.py`

- [ ] **Step 1: Add failing tests for all three provider routes**

Create a `Pipeline` fixture with mocked `comfy_asset` and a mocked loopback CDP daemon. For three speech utterances, assert:

- `image_provider='comfy'` calls the existing Qwen graph path for each scene.
- `image_provider='chatgpt'` calls `/api/images/generate` with a stable UUID task ID and exact scene prompt.
- `image_provider='flow'` calls `/api/flow/images/generate` serially with `task_id`, `job_id`, and exact scene prompt.

Assert each returned file is validated and copied to the job output; image checkpoint metadata binds hash, prompt, provider, and stable scene identity; no scene is re-requested on a retry when its checkpoint and receipt pass validation.

Also construct a legacy job request with no `image_provider` and assert it still routes to Comfy.

Run: `C:\Python312\python.exe -m unittest discover -s tests -p 'test_image_provider_routing.py' -q`
Expected: FAIL because `Pipeline.images` currently always uses Comfy in quick mode.

- [ ] **Step 2: Add stable job/scene task identity and provider dispatch**

Use a deterministic UUID5 identity for remote browser tasks:

```python
scene_task_id=str(uuid.uuid5(uuid.UUID(j['id']),f'bulk-scene-image:{i}'))
provider=j['request'].get('image_provider','comfy')
```

Keep the current Comfy branch unchanged for `comfy`. For ChatGPT and Flow, POST only to the existing loopback daemon routes, verify response task ID/path/hash, copy the validated image into `Path(j['output']) / f'images-{i:04}.png'`, then write the same durable per-image checkpoint. Use `trust_env=False`, loopback URL validation, and serialized calls. Do not use private Flow APIs or cookies.

- [ ] **Step 3: Preserve strict visual-QA mode**

At the top of `Pipeline.images`, when `gate_mode(j)=='required'`, retain the current Comfy/reviewer path. If the selected provider is not supported by that path, raise `PermanentError` before any generation call. Do not weaken `receipt_passes`, reviewer checks, or release gates.

- [ ] **Step 4: Run bulk routing and existing image tests**

Run:

```powershell
C:\Python312\python.exe -m unittest discover -s tests -p 'test_image_provider_routing.py' -q
C:\Python312\python.exe -m unittest discover -s tests -p 'test_comfy_scene_images.py' -q
C:\Python312\python.exe -m unittest discover -s tests -p 'test_visual_quality.py' -q
```

Expected: all PASS; legacy fallback remains Comfy and strict QA remains guarded.

- [ ] **Step 5: Commit**

```powershell
git add videostudio/providers.py tests/test_image_provider_routing.py
git commit -m "feat(images): route initial scene assets by provider"
```

## Task 5: Default Scene Editor rerenders to Flow and test the submitted provider

**Files:**
- Modify `static/scene-editor.js`
- Modify `scripts/test_scene_generation_ui.cjs`

- [ ] **Step 1: Add a failing test**

In the isolated Scene Editor regression, wait for provider discovery, assert Flow is the checked radio on a fresh scene, then select ChatGPT and Comfy in turn and verify the POST body uses the selected provider. Assert a completed Flow rerender adds a candidate option but does not change the active `edit_id` until the user explicitly selects it.

Run: `node scripts/test_scene_generation_ui.cjs`
Expected: FAIL because the fresh scene currently defaults to ChatGPT.

- [ ] **Step 2: Change the first-use default and keep provider discovery**

In `makeCard`, replace the first-use fallback `'chatgpt'` with `'flow'` for the checked radio and provider cache. Keep the API-reported `providers` list authoritative; if Flow is unavailable, disable it and select the existing ChatGPT fallback. Reorder visible radios to Flow, ChatGPT, Comfy. Preserve per-scene selections in the existing cache.

- [ ] **Step 3: Run the UI regression**

Run: `node scripts/test_scene_generation_ui.cjs`
Expected: PASS at 390 and 1280 widths; Flow selected by default; chosen provider is posted; candidate remains unapplied.

- [ ] **Step 4: Bump the Scene Editor asset version and commit**

Change `/scene-editor.js?v=20261026-flow1` to a new version only if this identifier was already used by a prior deployment; otherwise use it as the version. Then:

```powershell
git add static/scene-editor.js static/index.html scripts/test_scene_generation_ui.cjs
git commit -m "feat(ui): default new image generation to Flow"
```

## Task 6: Full verification and one conditional live smoke image

**Files:** no code changes expected unless a test finds a defect.

- [ ] **Step 1: Run full verification**

Run:

```powershell
C:\Python312\python.exe -m unittest discover -s tests -p 'test_*.py' -q
node scripts/test_initial_image_provider_ui.cjs
node scripts/test_scene_generation_ui.cjs
node scripts/test_editor_pagination.cjs
node --check static/scene-editor.js
C:\Python312\python.exe -m py_compile videostudio\core.py videostudio\providers.py videostudio\cdp_flow.py videostudio\scene_images.py videostudio\cdp_daemon.py videostudio\api.py
```

Expected: every command passes and both UI regressions report the selected provider plus unchanged scene on candidate generation.

- [ ] **Step 2: Check all external-work guards before deployment**

Confirm `active_jobs.py` is zero, no Flow scene task is queued/running, Comfy queue is idle, and exactly one Flow tab is open. Never restart ComfyUI or clear VRAM as part of this feature.

- [ ] **Step 3: Run at most one live Flow smoke image if free-cost is visible**

Use a dedicated test scene and the existing one Flow tab. Submit only if the on-page estimate explicitly reads 0 credits for each submit. Verify 2K download, task receipt, resulting image dimensions/hash, no duplicate Flow tab, and unchanged active scene image. If cost is nonzero/unclear, stop before Generate and report the gate result; do not switch provider automatically.

- [ ] **Step 4: Commit only intended files and deploy while workers are idle**

Use the existing VideoStudio restart script only after confirming active production/image workers are zero. Restart VideoStudio API/CDP only; do not restart Chrome or ComfyUI. Verify health and the single Flow tab after deployment.
