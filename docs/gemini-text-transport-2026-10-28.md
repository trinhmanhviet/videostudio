# Gemini as a second text transport (2026-10-28)

## What was added

VideoStudio can now run its text steps (`llm_json`) on **Gemini's visible web UI** in the same dedicated Chrome that already serves Flow and ChatGPT, without touching the image providers.

| Piece | File | Notes |
|---|---|---|
| Provider-qualified receipts | `videostudio/cdp_requests.py` | `prepare(job, prompt, provider='chatgpt')`. ChatGPT keeps the original `sha256(job\0prompt_hash)` identity so existing receipts still resolve; Gemini uses `sha256('gemini'\0job\0prompt_hash)`. |
| Provider-scoped conversations | `videostudio/cdp_requests.py` | `set_conversation(..., provider=)` / `conversation(..., provider=)`; ChatGPT rows keep the bare job key, Gemini rows use `job\0gemini`. Gemini URLs must be `https://gemini.google.com/...`. |
| Gemini DOM adapter | `videostudio/cdp_gemini.py` | Snapshot (composer, turns, chat text, streaming), composer focus point, send control, New chat control, reply correlation. |
| Daemon route | `videostudio/cdp_daemon.py` | `POST /api/gemini` → `ChromeChatGPTBridge.ask_gemini()`; same loopback/client-header/origin guards as `/api/chat`. |
| Transport choice | `videostudio/providers.py` | `VS_LLM_TRANSPORT=gemini` posts to `/api/gemini`; `cdp` keeps posting to `/api/chat`. No silent fallback between providers. Images are unaffected (`image_provider` untouched). |

## Safety rules actually enforced

1. **Receipt before input.** `journal.claim_send(identifier)` runs *before* the mouse press; a crash or ambiguity afterwards is recovery-only and never re-sent. Verified by `test_claimed_gemini_receipt_cannot_be_resubmitted`.
2. **Fresh chat only.** A new tab restores the owner's last conversation, so the adapter always clicks **New chat** before typing; it refuses to type if the control is missing.
3. **Exact send control.** The send button is matched only inside `input-area-v2` with the exact label `Gửi tin nhắn` / `Send message`. A bare `/gửi/` match also hits feedback buttons and silently swallows the request — that failure mode was observed live and is now covered by a test.
4. **Proof of dispatch.** After the click, the composer must clear within 6 s; otherwise the request is marked indeterminate.
5. **Reply identity.** A reply is accepted only when the transcript holds a parseable JSON object whose `request_id` equals this receipt, positioned after the request marker, not the envelope placeholder, on a not-streaming page. Duplicate markers raise ambiguity.
6. **Rendered chrome tolerated.** The current build wraps the JSON in a `JSON` chip and copy labels, so the object is extracted from the rendered text rather than assuming pure JSON.

## Live smoke (one request, ended by recovery, nothing resent)

- Job `gemini-smoke-20261028-130408`, receipt `fdbafcb53809936ddcf84419c246b1742fe672c9fbe19eb1b1d160e40bdcc680`.
- Prompt: harmless connectivity test asking for one JSON object `{"smoke":"c47598504847","ok":true}`.
- One message was sent in a **new** Gemini chat (`https://gemini.google.com/app/234c22bbc7dfc02f`). No video job, no image, no Flow interaction.
- Gemini replied with the exact envelope, correlated to that request id:
  `{"request_id": "fdbafcb5…dcc680", "result": {"your_response": {"smoke": "c47598504847", "ok": true}}}`
- The first polling pass did not accept it because the rendered reply is not bare JSON; the correlation logic was corrected and the **already-sent** reply was then recovered read-only and the receipt sealed as `completed`. Nothing was submitted a second time.
- Two earlier attempts typed into a tab but never dispatched (wrong control / no click proof). Both left unsent drafts, which were cleared, and those tabs were closed; their receipts remain `sending` and are never reused.

## Verification

- `python -m unittest discover -s tests -p "test_*.py" -q` → **293 tests OK** (includes the new `tests/test_gemini_text.py`, 24 tests).
- `python -m compileall -q videostudio` → clean.
- `scripts/active_jobs.py` → `0` before and after.

## Limits / next steps

- Only the text path was exercised. Gemini has not been used inside a real video job, and this run does not prove multi-step prompt stability over a full pipeline.
- The completion check depends on Gemini's current DOM (`user-query`, `model-response`, `input-area-v2`). Selector drift is a known risk (third-party report: selector brittleness); if the elements change, the adapter fails closed rather than guessing.
- `VS_LLM_TRANSPORT` is a global switch: switching a machine to `gemini` changes text for every job. Per-job provider selection would be a separate change.
- Unrelated dirty/untracked files in the worktree were left untouched; nothing was staged or committed.
