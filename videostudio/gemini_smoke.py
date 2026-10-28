"""Durable acceptance receipt for the dedicated-UI Gemini text transport.

Only an exact synthetic smoke reply recorded by the CDP daemon unlocks the
Gemini text gate; a socket connection or a ChatGPT smoke never does.
"""
import json
import os
import time
from pathlib import Path

SMOKE = {'connection_test': 'videostudio', 'ok': True}
MAX_AGE_SECONDS = 24 * 60 * 60


def receipt_path():
    return Path(os.getenv('VS_GEMINI_SMOKE', str(Path(__file__).resolve().parents[1] / 'data' / 'gemini-smoke.json')))


def normalize(value):
    """Accept the daemon's flat reply or its your_response envelope."""
    if isinstance(value, dict) and isinstance(value.get('your_response'), dict):
        return value['your_response']
    return value


def record_gemini_smoke(value):
    value = normalize(value)
    if value != SMOKE:
        raise ValueError('Exact Gemini smoke response required')
    path = receipt_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.part')
    temporary.write_text(json.dumps({'response': value, 'recorded': time.time()}), encoding='utf-8')
    temporary.replace(path)


def accepted_gemini_smoke():
    try:
        data = json.loads(receipt_path().read_text(encoding='utf-8'))
        return data.get('response') == SMOKE and time.time() - float(data.get('recorded', 0)) <= MAX_AGE_SECONDS
    except (OSError, ValueError, TypeError):
        return False
