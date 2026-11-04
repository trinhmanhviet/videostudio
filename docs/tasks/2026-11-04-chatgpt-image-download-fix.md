# Task: fix ChatGPT image detection + download in the CDP daemon

## Problem (observed 2026-11-04 ~02:00)
`scripts/make_meme_assets.py` calls `POST http://127.0.0.1:8879/api/images/generate` (header `X-VS-Client: videostudio`).
The daemon opens a new ChatGPT tab in the dedicated Chrome (CDP port 19223), sends the prompt, and ChatGPT
DOES draw the image. But `videostudio/cdp_images.py` never recognises the finished image, so it waits until
the timeout and never downloads. Closing the tab makes it fail with "Image conversation URL unknown".
Most likely ChatGPT changed its DOM. The code relies on:
- `[data-talvt-turn-state]` turns with state `complete`
- user turn found via `h4` text `You said:` / `Bạn đã nói:` containing the marker
- `button[data-testid="generated-image-preview"] img` (loaded, >=512px, src blob:https://chatgpt.com/ or https)
- viewer `[role=dialog]` with `button[aria-label="Download"|"Save"]`
See `image_snapshot`, `match_image`, `preview_expr`, `download_expr` in `videostudio/cdp_images.py`.

## Steps
1. In the dedicated VideoStudio Chrome, open a conversation that already has a finished generated image
   (tonight's attempts are in the ChatGPT sidebar). Run `C:\Python312\python.exe scripts\probe_chatgpt_image_dom.py`
   (read-only) and read `assets/Meme_Animation_Asset_Pack/new/_probe.json`. Inspect more via CDP if needed (read-only).
2. Update the selectors/logic in `cdp_images.py` to match the current DOM. Keep every safety invariant:
   exactly one Send, never auto-resend, correlate by the request marker, refuse when >1 image, download only via
   the visible Download control with CDP `Browser.downloadWillBegin/Progress` correlation, same validation.
3. Add/adjust unit tests (tests/) for `match_image` and the snapshot shape. Run the relevant tests.
4. Restart ONLY the CDP daemon (port 8879) so it loads the fix, and only if no video job is running
   (check `data/jobs.sqlite3`, table `jobs`, state `running`). If a job is running, stop and report instead.
5. Verify end to end: `C:\Python312\python.exe scripts\make_meme_assets.py --test` (2 images). Confirm
   `assets/Meme_Animation_Asset_Pack/new/bg_living_room.png` and `prop_food.png` exist and are real images.
   Do NOT run the full batch.
6. Do not commit. Report the files you changed and the test results.

## Do not
- Touch Flow / reCAPTCHA code, cookies, Chrome profile files.
- Delete user files. Commit secrets.
