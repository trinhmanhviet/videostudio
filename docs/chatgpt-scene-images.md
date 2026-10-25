# ChatGPT browser scene-image candidates

## Scope
ChatGPT is the first added regeneration provider. Google Flow is deliberately NOT implemented; no dormant private Flow endpoint is guessed. ComfyUI remains the existing bulk-production image provider; this change does not add a per-scene Comfy regeneration button or change its preferred Qwen model.

No new Chrome, OAuth credentials, paid image API or account is required. `cdp_images.py` is an adapter inside the existing dedicated CDP daemon and shares its browser/job lock, connection, authentication and durable RequestJournal. The result is an image file instead of JSON. Existing text requests retain their current response contract.

## User workflow
Open **Xem / sửa ảnh từng cảnh**, expand **Tạo lại bằng ChatGPT**, edit the scene visual prompt, click **Tạo ảnh ứng viên**. The tool sends ONLY the text description, not the original scene image/audio, to the dedicated logged-in ChatGPT web session. It uses that account's image quota. Generation is persistent and may take minutes. Close/reopen the editor and expand the same scene's section to see its recent requests.

The resulting candidate has a preview and **Dùng ảnh ChatGPT này** button. Until selected, neither editor version nor active image changes. Applying uses the existing cover/contain selection and immutable image-history mechanism, leaving speech, timing, captions, music and original MP4 intact. New exports are still separate jobs. This does NOT certify image content/historical truth.

No batch generation/automatic retry loop is enabled. At most ten queued/running image tasks are accepted; only one pending task per scene is allowed. Operators must explicitly resume uncertain/auth tasks, or stop waiting. Stopping tool waiting does not promise to cancel a request already running inside ChatGPT; no unrelated ChatGPT Stop button is clicked.

## Browser transaction
1. Store validates source job/scene/editor version and durably allocates a UUID task/idempotency key.
2. The worker acquires the same production lease and heartbeats it; no competing heavy stage is started in parallel.
3. `POST /api/images/generate` is loopback-only, same X-VS-Client/Origin guards as text. Prompt includes an exact request marker and asks for ONE portrait image, not a JSON answer.
4. Adapter creates its own image tab. It never borrows/navigates/closes an existing owner conversation. Text tab reuse now requires a recorded `owned_targets` text-purpose receipt; image tabs and other pages are not automatically closed.
5. New send requires verified Chat mode, no login/challenge, empty or exactly matching owned draft. RequestJournal changes prepared→sending BEFORE native Send. There is exactly one native click, no fallback second submission.
6. Response must contain one completed marker-correlated turn and one loaded generated-image-preview with valid dimensions. Missing/multiple/ambiguous results are not guessed from the last image on the page. Post-send read-only recovery may inspect an already-open image viewer (where mode controls are hidden), but pre-send always requires verified Chat.
7. Open the matching generated-image viewer, then its visible Download control. Match Browser.downloadWillBegin.frameId and GUID with completed downloadProgress; check bytes, pixel limits, format and SHA before accepting. Never capture a screenshot as the image or reconstruct a guessed private API request.
8. Store copies the attested file to an immutable candidate. User apply is transactional with editor version and timeline binding, provenance+request ID and the applied task receipt.

## Recovery and limits
- Unknown delivery never becomes a new request automatically. The same UUID + prompt reuses RequestJournal; sending state is recovery-only.
- Auth/challenge is returned as needs_auth for the owner to finish in the dedicated browser, not solved by code.
- Ambiguous state is uncertain, exposes **Kiểm tra lại yêu cầu cũ**. A missing exact conversation URL immediately after a send may need manual inspection; it must not guess a different chat or resend. Refusal/quota/image format failures surface explicitly.
- Candidate selection rejects stale editor versions and changed timeline. Another tab's edits do not get overwritten silently. Completed task IDs applied again only acknowledge the prior application.
- The queued/running task table is included in the idle-only service restart guard. Queued/running tasks survive service restart; worker reuses same request IDs. Browser lock wait can still exceed HTTP timeout during a stalled text session; that becomes uncertain rather than an automatic resend.
- Download settings are temporarily changed only in the VideoStudio-owned Chrome and restored to default afterwards. Existing generated-content provenance embedded in image bytes is not stripped by the download adapter.
- ChatGPT UI selectors may change. Unsupported state must stop rather than pretend success. This is not a promise of permanent login, unlimited image quota or perfect generated imagery.

## Verification actually performed
- A single exploratory image request in an explicitly new dedicated tab generated a red-apple PNG941x1672. Native viewer Download produced the file, owned-frame/GUID correlation and SHA256 `423cf98d052835be6fc57221bf7906eebf193f4859064bc7ac4a28efe15bafe6`.
- The implemented adapter's `_download` was then exercised LIVE against that existing image, without sending another prompt, and returned the SAME SHA. An initial verification exposed hidden-viewer mode + foreground activation issues; both were fixed before successful rerun. Evidence `data/chatgpt-image-live-verification/download-verification.json` and `download-events.json`.
- Automated recovery test starts with a sending receipt, recovers a matching image without Input.insertText/Send, caches its completed receipt and does not call the browser on the next identical request.
- Queue/API tests cover idempotency, no implicit apply, stale apply, immutable task application, request scoping, blocked providers, file path escape/hash/size validation, uncertain/manual-resume, cancellation and production lease exclusion.
- Isolated real-Chromium UI tests mock all generation mutations and prove one create/one explicit apply at390px and1280px, with scene duration unchanged and compact header retained. Existing layout tests verify360/390/480/landscape/desktop. These UI tests are NOT a new live end-to-end ChatGPT submission through the product UI.
- No armor production scene was regenerated/replaced/exported in implementation testing. Google Flow and automated visual-content QA remain out of scope.

Commands:

```powershell
C:\Python312\python.exe -m unittest discover -s tests -p 'test_*.py' -q
node scripts/test_scene_generation_ui.cjs
node scripts/test_scene_editor_layout.cjs
```
