# Follow-up integration evidence

Owner explicitly authorized starting the existing local PostgreSQL container, read-only voice inventory export, and then inspecting/starting the existing local ChatGPT2API container. No web, tunnel, API or production-worker containers were started.

## Authoritative voices

`scripts/import_voices.py` performs a read-only PostgreSQL transaction. Result: 25 canonical presets, 3 locked clones, 3 archived clone records. All 3 locked reference WAV SHA-256 values match authoritative DB hashes. Export is local-only under ignored `data/voices-export.json`, not in Git. Original media and DB records are unchanged. Archived voices are retained but disabled for new selection.

## Existing speech runtime

`D:/Projects/storyforge/.runtime/media-gpu/.venv/Scripts/python.exe` can locate the vieneu package. This is an environment discovery, not a successful speech-generation test. Cache/model and safe GPU execution still need integration.

## LLM probe

Existing configured loopback endpoints initially did not respond. After owner-authorized start of `storyforge-chatgpt2api-chatgpt2api-1`, an authenticated GET `/v1/models` returned HTTP 200. No credential value was printed or copied. Configured model `gpt-5-5` is absent from returned IDs. Returned IDs include auto, gpt-5-3-mini, gpt-5-6, gpt-5-6-mini, gpt-6, gpt-6-mini and gpt-image-2. A model catalog response does not establish an authenticated, working generation session or supported unattended operation. No completion request was sent. Deployment source labels this proxy a personal experiment. Its suitability and safeguards must be established before relying on it for production.

## Tests after import changes

14 unittest tests passed in 5.456 seconds. These remain fixture/unit/backend tests, not AI generation acceptance. Production readiness remains blocked for outstanding implementation requirements described in README.md.

## Running service changes

Only the two owner-authorized containers were started. They are left running for continued integration, not stopped without permission. No existing online site, old video, model or source StoryForge code was modified.
