# Video creation through the ordinary-Chrome extension

The owner confirmed the background ChatGPT bridge works, then requested connecting it to video creation so they could test the next step.

## Observed cause and activation

Read-only checks showed the bridge was active and its text smoke was recorded, while the running video server's preflight still selected **Gemini**. The existing scoped job/exchange integration was already present; the running server configuration selected the wrong text transport.

After tests and an idle check (zero active video/image jobs), `scripts/start_extension.ps1 -RestartOwnServer` restarted only the owned VideoStudio API. New API PID: 45904. The existing image/browser daemon on 8879 retained PID 38672. No Chrome/Comfy restart, live prompt or new production video was initiated.

Post-start checks recorded in `data/extension-video-activation.json` confirmed:

- `text_transport: extension`, `worker_enabled: true`.
- Existing scope `4337ffc2-560c-4604-9f00-49f0f1c70a2a` retained its active heartbeat and completed smoke.
- Scoped preflight returned `ready: true`, with extension transport, voice, FFmpeg, Comfy nodes/models and music acceptance checks passing.

## UI and integration verification

The health and preflight responses now expose `text_transport`. The main video tool follows extension mode: it selects ChatGPT through the ordinary-Chrome bridge, locks out incompatible Gemini selection and hides dedicated-browser setup controls for text. Scoped video creation retains its connector-scope header; pipeline text calls use that scope's immutable exchanges. Image/music generation keeps the existing providers.

`tests/test_extension_video_connection.py` exercises real API job allocation, scoped binding, Worker, Pipeline plan/research/script, exchange polling and response import using fixture JSON responses. It confirms distinct request IDs and unchanged supplied narration, and disallows CDP/paid-API text calls. It deliberately stops before speech/media generation.

- Python regression: 314 tests OK, 49.405s; log `data/extension-video-regression.txt`.
- Extension regression: 28 tests pass.
- Intercepted real-Chromium UI checks: eight pass, including the main video form following the server's extension mode.

## Next owner test

Reload the **existing connected Studio tab**, select/open a project, fill in the idea or supplied narration, voice, duration and image provider, then use **Bắt đầu tạo video**. Keep that Studio tab open while the extension handles text requests in background ChatGPT tabs. No extension reload is needed for this backend/UI change. For a future server launch, use `scripts/start_extension.ps1` to preserve the extension mode; the generic launcher's explicit alternative modes remain available.

Passing preflight and fixture integration do not assert that a new complete AI video has passed end-to-end acceptance. The owner is performing that next test.
