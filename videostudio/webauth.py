"""Fail-closed, SSE-only AICoworker WebAuth text adapter. No automatic re-submission."""
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import httpx
from .core import PermanentError

MODEL = 'webauth-chatgpt-gpt'
DEFAULT_CONFIG = Path.home() / 'aicoworker' / 'openclaw' / 'openclaw.json'
SMOKE_RESPONSE = {'connection_test': 'videostudio-webauth', 'ok': True}


def accepted_smoke():
    path = Path(os.getenv('VS_WEBAUTH_SMOKE', str(Path(__file__).resolve().parents[1] / 'data' / 'webauth-smoke.json')))
    try:
        receipt = json.loads(path.read_text(encoding='utf-8'))
        return (receipt.get('completed') is True and receipt.get('model') == MODEL
                and receipt.get('response') == SMOKE_RESPONSE)
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def configuration():
    path = Path(os.getenv('VS_WEBAUTH_CONFIG', str(DEFAULT_CONFIG)))
    try:
        provider = json.loads(path.read_text(encoding='utf-8'))['models']['providers']['webauth']
        base = provider['baseUrl']
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PermanentError('WebAuth proxy configuration unavailable') from exc
    parsed = urlparse(base)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path.rstrip('/') != '/v1' or parsed.port is None):
        raise PermanentError('WebAuth proxy must be a loopback HTTP /v1 endpoint')
    return base.rstrip('/')


def parse_sse(lines):
    chunks=[];finish=None;done=False;event=[];event_type=None
    def consume():
        nonlocal finish, done, event
        if not event:return
        payload='\n'.join(event);event=[]
        if payload=='[DONE]':done=True;return
        try:record=json.loads(payload)
        except ValueError as exc:raise PermanentError('Invalid WebAuth SSE JSON') from exc
        if event_type=='error' or not isinstance(record,dict) or record.get('error'):
            raise PermanentError('WebAuth returned an error event')
        choices=record.get('choices')
        if not isinstance(choices,list) or len(choices)!=1 or not isinstance(choices[0],dict):
            raise PermanentError('Invalid WebAuth SSE choice')
        choice=choices[0];delta=choice.get('delta',{})
        if not isinstance(delta,dict):raise PermanentError('Invalid WebAuth SSE delta')
        content=delta.get('content')
        if content is not None:
            if not isinstance(content,str):raise PermanentError('Invalid WebAuth SSE content')
            chunks.append(content)
        if choice.get('finish_reason') is not None:
            if finish is not None:raise PermanentError('Duplicate WebAuth finish event')
            finish=choice['finish_reason']
    for line in lines:
        if isinstance(line,bytes):line=line.decode('utf-8')
        if not line:
            consume();event_type=None;continue
        if done:raise PermanentError('WebAuth SSE data after terminal marker')
        if line.startswith(':'):continue
        field,sep,value=line.partition(':')
        if sep and value.startswith(' '):value=value[1:]
        if field=='event':event_type=value
        elif field=='data':event.append(value)
    if event:raise PermanentError('Truncated WebAuth SSE event')
    if not done or finish!='stop' or not chunks:raise PermanentError('Incomplete or refused WebAuth response')
    try:result=json.loads(''.join(chunks))
    except ValueError as exc:raise PermanentError('WebAuth returned invalid JSON content') from exc
    if not isinstance(result,dict):raise PermanentError('WebAuth JSON object required')
    return result


def request_json(prompt,check):
    base=configuration()
    payload={'model':MODEL,'messages':[{'role':'user','content':prompt}], 'stream':True}
    check()
    try:
        with httpx.Client(timeout=360,trust_env=False) as client:
            with client.stream('POST',base+'/chat/completions',json=payload) as response:
                if response.status_code!=200:raise PermanentError('WebAuth HTTP '+str(response.status_code))
                if 'text/event-stream' not in response.headers.get('content-type','').lower():
                    raise PermanentError('WebAuth must return SSE')
                result=parse_sse(response.iter_lines())
    except (httpx.HTTPError,UnicodeError) as exc:
        # The proxy may have delivered the prompt before the connection failed.
        # A permanent failure prevents Core's generic retry loop from resending it.
        raise PermanentError('WebAuth delivery uncertain; do not automatically resubmit this text request') from exc
    check()
    return result
