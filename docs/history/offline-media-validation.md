# Offline media improvements and actual validation

Parent engineer reran `python -m compileall -q videostudio` and `python -m unittest discover -s tests -v`: 19 tests passed in 6.998 seconds.

New tests cover Vietnamese accent/text preservation, caption width rejection, overlapping-cue rejection, measured utterance cue serialization and actual CPU encoding of two distinct fixture-image scenes. FFprobe checks 1080x1920 and 30/1 frame rate. Fixture speech/music is sine-wave audio, NOT VieNeu or Stable Audio output.

Changes: per-scene cached pan/zoom visual clips with hashes; no narration atempo or truncation; bounded visual tail hold; audio fade, sidechain ducking and limiter; per-utterance speech caching and measured caption intervals; per-scene image checkpoints; queue and free-VRAM guard before new Comfy submissions with no global unload/interrupt.

Unverified: provider-generated storyboard to real VieNeu chunks, image semantics/continuity, regeneration of bad scenes through a bounded quality repair loop, natural-duration script rewrite, crossfade looping music, voice clipping/missing-word detection, GPU race-free coordination across other tools and Docker integration. Caption cues are utterance-level timing, NOT word-level forced alignment. Current duration validation 8-600s is an unvalidated scaffold limit, not an established production capability. Production readiness remains false.

LLM live test remains blocked by upstream 403. No further LLM request, GPU generation or model download was performed during this offline work.
