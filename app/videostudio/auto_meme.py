"""Resumable local API client; never calls generation providers directly."""
import argparse
import hashlib
import json
import math
import os
import sys
import time
import uuid
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

DEFAULT_VOICE = 'clone:18cad821-0d87-461f-a443-d45db92e36e9'


def receipt_path(output):
    return Path(str(output) + '.auto-meme.json')


class ClientError(Exception):
    pass


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ClientError('API redirects are not allowed')


class Client:
    def __init__(self, server):
        parsed = urlsplit(server)
        if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
                or parsed.username or parsed.password or parsed.path not in ('', '/')
                or parsed.query or parsed.fragment):
            raise ClientError('--server must be an HTTP localhost origin, such as http://127.0.0.1:8877')
        try:
            parsed.port
        except ValueError as error:
            raise ClientError('Invalid server port') from error
        self.server = server.rstrip('/')
        self.opener = build_opener(ProxyHandler({}), NoRedirects())

    def open(self, path, payload=None, headers=None):
        if not path.startswith('/api/') or path.startswith('//'):
            raise ClientError('Invalid local API path')
        body = None if payload is None else json.dumps(payload).encode('utf-8')
        request = Request(self.server + path, data=body,
                          headers={'Content-Type': 'application/json', **(headers or {})})
        try:
            return self.opener.open(request, timeout=60)
        except HTTPError as error:
            detail = error.read(8192).decode('utf-8', errors='replace')
            raise ClientError(f'API HTTP {error.code}: {detail}') from error
        except (URLError, OSError) as error:
            raise ClientError(f'Cannot reach local VideoStudio API: {error}') from error

    def json(self, path, payload=None, headers=None):
        with self.open(path, payload, headers) as response:
            result = json.load(response)
        if not isinstance(result, dict):
            raise ClientError('Invalid API JSON response')
        return result


def discover_scope(client, requested=None):
    candidates = [requested] if requested else [item.get('scope') for item in
                 client.json('/api/connector/status').get('items', []) if isinstance(item, dict)]
    problems = []
    for scope in dict.fromkeys(candidates):
        if not isinstance(scope, str) or not scope:
            continue
        try:
            status = client.json('/api/connector/bridges/' + quote(scope, safe='') + '/status')
            if status.get('ready') is not True or status.get('bridge') != scope:
                problems.append(f'{scope}: bridge is not ready'); continue
            preflight = client.json('/api/preflight?' + urlencode({
                'scope': scope, 'workflow_mode': 'meme'}))
            if preflight.get('ready') is not True:
                checks = [c.get('message') or c.get('name') for c in preflight.get('checks', []) if not c.get('ok')]
                problems.append(f'{scope}: preflight blocked: {checks}'); continue
            return scope
        except ClientError as error:
            problems.append(str(error))
    raise ClientError('No ready connector root. Start and test the Studio extension bridge. ' + '; '.join(problems))


def digest_file(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def save_receipt(path, receipt, initial=False):
    value = json.dumps(receipt, ensure_ascii=False, indent=2) + '\n'
    if initial:
        with path.open('x', encoding='utf-8') as stream:
            stream.write(value)
    else:
        temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            temporary.write_text(value, encoding='utf-8')
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def run(args):
    client = Client(args.server)
    output = Path(args.out).expanduser().resolve()
    if output.suffix.lower() != '.mp4':
        raise ClientError('--out must name an MP4 file')
    idea = Path(args.input).read_text(encoding='utf-8-sig').strip() if args.input else args.idea.strip()
    if not idea or len(idea) > 100000 or not args.voice.strip() or not math.isfinite(args.seconds) or not 15 <= args.seconds <= 600:
        raise ClientError('Provide 1–100000 characters of input, a voice, and --seconds between 15 and 600')
    if not math.isfinite(args.poll_seconds) or args.poll_seconds <= 0:
        raise ClientError('--poll-seconds must be positive')
    payload = {'idea': idea, 'workflow_mode': 'meme',
               'voice_id': args.voice, 'duration_seconds': args.seconds, 'project': args.project,
               'text_provider': 'chatgpt', 'image_provider': 'comfy', 'flow_batch_size': 1,
               'music_volume': 0, 'quality_mode': 'quick'}
    request_hash = hashlib.sha256(json.dumps({'server': client.server, 'request': payload},
                                            sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    legacy_hash = hashlib.sha256(json.dumps({'server': client.server, 'request': {**payload,'meme_engine':'hyperframes'}},
                                           sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    receipt_file = receipt_path(output)
    receipt = json.loads(receipt_file.read_text(encoding='utf-8')) if receipt_file.exists() else None
    if receipt is not None:
        if (not isinstance(receipt, dict) or receipt.get('request_hash') not in (request_hash,legacy_hash)
                or receipt.get('server') != client.server or not receipt.get('idempotency_key')
                or (args.scope and receipt.get('scope') != args.scope)):
            raise ClientError('Output receipt belongs to a different request; choose another --out')
    if output.exists():
        if receipt and receipt.get('output_sha256') and digest_file(output) == receipt['output_sha256']:
            print(f'Already saved: {output}'); return 0
        raise ClientError(f'Refusing to overwrite existing output: {output}')
    if receipt is None:
        scope = discover_scope(client, args.scope)
        output.parent.mkdir(parents=True, exist_ok=True)
        receipt = {'version': 1, 'request_hash': request_hash, 'server': client.server,
                   'idempotency_key': str(uuid.uuid4()), 'scope': scope, 'job_id': None}
        save_receipt(receipt_file, receipt, initial=True)
    if not receipt.get('job_id'):
        result = client.json('/api/jobs', payload,
                             {'Idempotency-Key': receipt['idempotency_key'], 'X-Connector-Scope': receipt['scope']})
        job = result.get('job', result)
        if not isinstance(job, dict) or not isinstance(job.get('id'), str) or not job['id']:
            raise ClientError('Submission response has no job ID; rerun to recover with the saved key')
        receipt['job_id'] = job['id']
        save_receipt(receipt_file, receipt)
    job_path = '/api/jobs/' + quote(receipt['job_id'], safe='')
    previous = None
    while True:
        job = client.json(job_path)
        status = job.get('status', job.get('state'))
        progress = (status, job.get('stage'), job.get('progress'))
        if progress != previous:
            print(f"Job {receipt['job_id']}: {status} | {job.get('stage') or '-'} | {job.get('progress', '?')}%", flush=True)
            previous = progress
        if status == 'completed':
            break
        if status in ('failed', 'cancelled', 'awaiting_visual_review', 'awaiting_flow_account'):
            raise ClientError(f"Job {status}: {job.get('error') or job.get('diagnostics') or 'Open Studio for details'}")
        if status not in ('queued', 'running', 'retrying', 'cancelling'):
            raise ClientError(f'Unknown job status: {status}')
        time.sleep(args.poll_seconds)
    download = job_path + '/files/video.mp4'
    if job.get('output_url') != download:
        raise ClientError('Completed job has no matching local video output')
    temporary = output.with_name(output.name + '.' + uuid.uuid4().hex + '.part')
    try:
        with client.open(download) as response, temporary.open('xb') as destination:
            while chunk := response.read(1024 * 1024):
                destination.write(chunk)
        if temporary.stat().st_size == 0:
            raise ClientError('Completed output is empty')
        # Hard-link publication is atomic and fails if any file already occupies --out.
        os.link(temporary, output)
        receipt['output_sha256'] = digest_file(output)
        save_receipt(receipt_file, receipt)
    finally:
        temporary.unlink(missing_ok=True)
    print(f'Saved: {output}')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--input', help='UTF-8 story text file')
    source.add_argument('--idea', help='Story idea or full text')
    parser.add_argument('--out', required=True, help='Destination MP4 (existing files are preserved)')
    parser.add_argument('--voice', default=DEFAULT_VOICE)
    parser.add_argument('--seconds', type=float, default=60)
    parser.add_argument('--project', default='Meme Animation')
    parser.add_argument('--scope', help='Existing ready extension bridge root (otherwise discovered)')
    parser.add_argument('--server', default='http://127.0.0.1:8877')
    parser.add_argument('--poll-seconds', type=float, default=2)
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (ClientError, HTTPException, OSError, ValueError, TypeError, KeyError) as error:
        print(f'auto_meme: {error}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('Interrupted. Rerun the same command to resume the saved job.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
