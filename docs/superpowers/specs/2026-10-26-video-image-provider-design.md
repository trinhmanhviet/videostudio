# Video image-provider selection

**Status:** User-approved design, awaiting written-spec review before implementation
**Date:** 2026-10-26
**Project:** `D:\Projects\videostudio`

## Goal

Let a user select the image-generation provider for a new VideoStudio video job and for later per-scene rerenders. Offer Flow, ChatGPT, and Comfy. Default both controls to Flow.

The selection on the initial video form applies to every scene image generated for that job. It is stored with the job request, not as a permanent project-wide preference. Existing jobs without the field keep their historical Comfy behavior.

## User-visible behavior

### New video job

- Add an image-provider selector to the existing **Tạo video trong dự án này** form.
- Choices: **Google Flow**, **ChatGPT**, **ComfyUI · Qwen Image 2.1**.
- Initial value: **Google Flow**.
- Submit the selected value as `image_provider` in the job request.
- The selected provider is used sequentially for all scene images in that job's initial image stage.

### Per-scene rerender

- Keep the existing three provider radios in the Scene Editor.
- The first-use default becomes Flow; users can still select ChatGPT or Comfy per scene.
- Flow results enter the existing candidate list. Generating a rerender never replaces the active scene image. Explicit user selection remains the only apply action.

## Provider behavior

### Flow

- Use the existing VideoStudio-owned, headed Chrome/CDP session and visible Google Flow UI only. Do not call private Flow APIs, replay requests, or access cookies.
- Enforce one Flow tab. Use one dedicated Flow project per VideoStudio video job and reuse it across every scene in that job. Do not use or alter the user's existing demo project.
- Serialize Flow generations through the shared browser lock. Each scene operation stores a durable task receipt, project URL, prompt hash, pre-submit state, and download result so an interrupted job can reconcile the same scene without blindly resubmitting.
- Before **every** Generate click, verify Agent/Tác nhân is off and the selected settings are Image, Nano Banana 2.1, 9:16, and x1. The visible UI must explicitly state that the generation costs exactly 0 credits. If any condition is missing, ambiguous, or nonzero, do not click Generate and fail closed with a scene-specific error.
- Wait for the scene output, use the visible image menu to download at 2K, correlate the download to the Flow tab/frame, validate the file and dimensions, then make it available to the job's image pipeline.
- If authentication, CAPTCHA, or verification is required, do not solve or bypass it. Stop without submitting and report that human sign-in is needed.
- Never generate Flow scenes in parallel. Progress and recovery remain bound to the same VideoStudio job/scene identity.

### ChatGPT

- Reuse the existing visible-UI ChatGPT image adapter in the dedicated Chrome browser.
- Preserve its current request receipts, authentication checks, no-blind-resubmit rule, and image validation.

### ComfyUI

- Use the existing Qwen Image 2.1 graph and bulk pipeline behavior.
- Keep shared-queue checks, bulk free-VRAM admission, receipts, output validation, and current worker safeguards unchanged. The separately authorized manual per-scene Comfy rerender behavior remains scoped to that UI action.

## Job data and backward compatibility

- Add `image_provider` with allowed values `flow`, `chatgpt`, and `comfy` to request validation and persisted job requests.
- New API/UI requests that omit it default to `flow`.
- Already-persisted jobs that do not contain it default to `comfy` when their image stage resumes. Do not reinterpret historic jobs as Flow jobs.
- Voice-change derived jobs reuse their existing images and do not start an image-generation stage.
- Do not loosen idempotency or worker retry rules. Provider and prompt are part of the persisted job request.

## Visual-QA mode

The current user-facing form submits `quality_mode=quick`. Provider selection applies to that normal initial-image path. The separate `required` visual-QA path retains its existing Comfy/reviewer admission gates; this change must not bypass visual review or falsely attest an image. If another client requests a provider combination unsupported by that strict path, fail before image submission with an explicit validation error.

## Failure and recovery rules

- Flow reports nonzero/unknown cost: fail before Generate; no automatic provider switch.
- Missing settings, multiple Flow tabs, wrong Flow project, occupied/draft UI, or unrecognized controls: stop before submitting and preserve the current tab/project.
- Failure after Generate may have been clicked: keep the durable receipt and reconcile only the same project/task. Never create a replacement task or resend a prompt automatically.
- Flow download errors may be retried only as retrieval of the already-generated result in the same project, never as another generation.
- Comfy busy/low-VRAM, ChatGPT authentication, and all existing provider-specific failures retain their current semantics.

## Data flow

1. The new-job form sends `image_provider` with the current job request.
2. `Pipeline.images` dispatches each scene sequentially to the selected adapter.
3. Each adapter writes a validated scene image into the job output, with stable per-job/per-scene identity and receipts.
4. Existing image checkpointing and video render stages consume the resulting assets.
5. In the Scene Editor, provider choice is independent and defaults to Flow. Rerender output follows the existing completed-candidate, explicit-apply path.

## Verification

- Request validation accepts each provider, rejects unknown values, defaults new requests to Flow, and keeps missing-field legacy requests on Comfy.
- Form UI emits the selected provider and displays all three options with Flow selected initially.
- Bulk image-stage tests prove provider dispatch for Flow, ChatGPT, and Comfy; deterministic IDs and receipts survive retries; legacy jobs still use Comfy.
- Flow tests prove one tab, one project reused for the same video job, serialization, Agent-off/settings/zero-credit checks before Generate, zero-credit rejection before submission, 2K download correlation/validation, and same-request recovery without duplicate generation.
- Scene Editor tests prove Flow is the default, all providers remain selectable, zero-credit/Flow-check statuses can be resumed with the same task, and rerender candidates are not applied implicitly.
- Run the full test suite. Perform at most one live Flow smoke image only after the visible Flow UI confirms 0 credits; confirm the job scene remains unchanged and the asset is delivered to its image pipeline.
