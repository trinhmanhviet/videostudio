"""Send one synthetic text request through the dedicated Gemini tab.

The CDP daemon records the acceptance receipt only for an exact reply. Run this
when the gate has expired; it never starts a video job and never repeats a
request on failure.
"""
import json
import sys

import httpx


def main():
    daemon = 'http://127.0.0.1:8879'
    prompt = 'Return exactly one JSON object and nothing else: {"connection_test":"videostudio","ok":true}'
    try:
        response = httpx.post(daemon + '/api/gemini', json={'prompt': prompt, 'job_id': '__acceptance__', 'timeout_seconds': 240},
                              headers={'X-VS-Client': 'videostudio'}, timeout=300, trust_env=False)
        response.raise_for_status()
        payload = response.json()
    except Exception as error:
        print('Gemini smoke failed; no receipt written:', type(error).__name__, str(error)[:300])
        return 1
    data = payload.get('data') or {}
    inner = data.get('your_response') if isinstance(data.get('your_response'), dict) else data
    if inner != {'connection_test': 'videostudio', 'ok': True}:
        print('Gemini replied but not with the exact smoke JSON; no receipt accepted:', json.dumps(inner)[:300])
        return 1
    from videostudio.gemini_smoke import accepted_gemini_smoke
    if not accepted_gemini_smoke():
        print('Reply matched but no fresh receipt was recorded by the daemon; check daemon logs.')
        return 1
    print('Gemini text smoke accepted and receipt recorded.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
