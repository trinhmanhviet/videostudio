# Live component progress, not full-product acceptance

## Chrome

Owner reloaded existing extension and clicked the explicit engineering test page. Server stored immutable exchange 64293a96-d410-4523-8ecb-14d343d6e948, scope 7ef68fc4-1143-4812-b2a3-fce83954dc18, response {"connection_test":"videostudio","ok":true}. This is real browser-mediated JSON completion, not a fixture. Receipts remain correlated by scope/id/version. The original Studio-tab ownership dependency remains, so tab-close unattended generation is not accepted.

## VieNeu

The existing CPU Python D:/Projects/storyforge/.runtime/media/.venv/Scripts/python.exe and offline model-cache were used with backend=onnx, device=cpu. Clone ID clone:d4f6b4b1-1af3-4bc3-a922-06ac47914c25 was preserved and its reference checksum checked. Actual 4.32-second PCM s16le mono 48kHz speech was generated. Full FFmpeg decode passed; all samples finite, RMS 0.07925, peak 0.74789, non-silent. No semantic listening/ASR completeness claim. Project artifacts are under E:/Videos/videostudio-tts-test-20261024-012453. A small playback copy is in the agent workspace media directory; no model/cache moved to C:.

## Code and tests

Added bounded duration rewrite orchestration with per-attempt script files, unchanged voice/target, no atempo. Two fixture tests prove finite attempts and fail-on-exhaustion, not live script acceptance. Added local soundtrack crossfade extension and fixed a timestamp issue discovered by actual encoding tests. Complete Python suite: 27 tests passed in 19.694 seconds. Existing connector 84 tests and 3 new scope tests previously passed.

## GPU blocker

Comfy queue was empty, but available VRAM fell to approximately 470MB of 24GB at the recorded probe. No new Qwen or Stable Audio request was submitted; no /free, /interrupt or process kill used. VideoStudio cannot prove ownership of the resident memory, so it does not unload it. An empty queue alone is not permission to unload another application's models.

Installed Comfy source explicitly implements StableAudio3; the native installed audio_stable_audio_3_medium_base.json template has checkpoint, T5Gemma encoder, KSampler 50/cfg7/lcm/simple and audio decoder parameters corresponding to the source-derived graph. Checkpoint safetensors header contains the expected seconds-total conditioning and shared-global tensors. This is source/asset compatibility evidence ONLY, not successful generation or a commercial licensing claim.

## Outstanding

Real Qwen/Stable Audio execution and meaningful QA; GPU safe coordination; automatic research and fact verification beyond local corpus; live duration rewrite across requested lengths; tab-close unattended behavior; container host routing/media runtime/volumes; full AI idea-to-final-video runs with multiple lengths and restart/fault tests. Production remains disabled. No complete video has been delivered or claimed.
