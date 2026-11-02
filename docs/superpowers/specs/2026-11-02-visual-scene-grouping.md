# Automatic visual scene grouping

Approved in chat: group related narration by visual context automatically, without user review or another LLM round. A change of location, time, visible subject or action starts a new visual scene. Caption length and sentence count do not define image boundaries.

New production plans carry `visual_grouping_version: 1`. Plans and chapter caches without that marker retain their existing behavior; saved script/speech/image checkpoints are never regrouped. The short and chapter script prompts use the same grouping rules. Each visual scene keeps its complete narration and independently caption-safe `narration_lines`; malformed or incomplete line metadata is rebuilt locally from narration, without another model call.

Targeted factual repair must also rebuild a changed scene's caption lines from its corrected narration, preserving its scene ID. A grouped scene's complete narration is not constrained to one caption's length.

For supplied narration, the existing visual-metadata response may identify adjacent lines with the same `visual_group_id`. Merge only explicit, contiguous groups with the same visual prompt and character set. Missing or inconsistent group metadata keeps separate scenes. Preserve all original text and line IDs in the supplied-narration manifest.

Reuse the existing speech hierarchy, per-scene image generation, caption timestamps and renderer. Assign deterministic scene IDs before any media generation. Validate short/chapter/supplied modes, old-cache resume, stable IDs, character references and the image-to-utterance timeline. No service restart, browser operation or live AI request is part of implementation verification.
