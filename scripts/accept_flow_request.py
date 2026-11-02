"""Run the requested real Flow acceptance sequence through the paired extension.

Each stage has one stable request ID. Run stages individually while inspecting
the new project; repeating a command only reconciles that same bridge receipt.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import uuid

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from FlowAPI.client import FlowRequestClient, FlowRequestFailure

STAGES = ('project', 'character', 'portrait', 'with-reference', 'without-reference')
PORTRAIT = (
    'Studio portrait of a fictional Vietnamese male botanist, age 32, warm medium skin, '
    'short straight black hair, round thin-rimmed glasses, moss-green field jacket and '
    'a mustard-yellow scarf. Chest-up, facing the camera, neutral light gray background, '
    'soft daylight, photorealistic. One person only, no text, no logo.'
)
WITH_REFERENCE = (
    'The same Vietnamese botanist as the attached Character reference, wearing the same '
    'moss-green field jacket, mustard-yellow scarf and round glasses, gently watering '
    'a small bonsai on a wooden table in a bright greenhouse. Preserve his face, hair '
    'and clothing. Photorealistic, one person, no text, no logo.'
)
WITHOUT_REFERENCE = (
    'Photorealistic still life of a small terracotta teapot and two ivory ceramic cups '
    'on a wooden table beside a green fern, soft morning sunlight, tranquil Vietnamese '
    'courtyard, no people, no text, no logo.'
)


def save(path, state):
    temporary = path.with_suffix('.json.part')
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf8')
    temporary.replace(path)


def arguments(stage, state, use_existing_ui_portrait=False):
    results = state['results']
    if stage == 'project':
        return 'create_project', {'name': state['project_name']}
    project = results['project']['project_id']
    if stage == 'character':
        return 'create_character', {'project_id': project, 'name': 'Minh_Botanist'}
    character = results['character']['character_id']
    if stage == 'portrait':
        return 'generate_image', {'project_id': project, 'target_character_id': character, 'prompt': PORTRAIT}
    if stage == 'with-reference':
        # A Character with no portrait is not a successful reference test.
        if not results.get('portrait', {}).get('images'):
            control = state.get('ui_controls', {}).get('portrait', {})
            image = Path(control.get('file', ''))
            valid_control = (use_existing_ui_portrait and control.get('state') == 'completed'
                             and control.get('character_id') == character and image.is_file()
                             and hashlib.sha256(image.read_bytes()).hexdigest() == control.get('sha256'))
            if not valid_control:
                raise ValueError('Finish the Character portrait before testing an image with its reference')
        return 'generate_image', {'project_id': project, 'prompt': WITH_REFERENCE,
                                  'references': [{'character_id': character, 'name': 'Minh_Botanist'}]}
    return 'generate_image', {'project_id': project, 'prompt': WITHOUT_REFERENCE, 'references': []}


def download_result(folder, stage, result):
    image = result['images'][0]
    data = bytearray()
    # Use only the returned HTTPS image URL; do not send browser/session headers.
    with httpx.stream('GET', image['url'], timeout=45, follow_redirects=False, trust_env=False) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            data.extend(chunk)
            if len(data) > 25 * 1024 * 1024:
                raise ValueError('Returned image exceeds 25 MiB')
    with Image.open(io.BytesIO(data)) as picture:
        width, height = picture.size
        extension = {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp'}.get(picture.format)
        picture.verify()
    if not extension:
        raise ValueError('Unsupported returned image format')
    output = folder / f'{stage}.{extension}'
    if output.exists() and output.read_bytes() != data:
        raise ValueError('A different downloaded image already occupies this acceptance stage')
    output.write_bytes(data)
    return {'path': str(output.resolve()), 'width': width, 'height': height,
            'sha256': hashlib.sha256(data).hexdigest(), 'image_id': image['image_id']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, help='UUID for this acceptance run, reused across every stage')
    parser.add_argument('--stage', choices=STAGES, required=True)
    parser.add_argument('--server', default='http://localhost:8878')
    parser.add_argument('--client-id')
    parser.add_argument('--attempt', type=int, default=1,
                        help='Explicit new attempt after an authoritative rejection; earlier receipts are retained')
    parser.add_argument('--use-existing-ui-portrait', action='store_true',
                        help='Use the separately verified native-UI portrait as input; never count it as a successful portrait RPC')
    options = parser.parse_args()
    run = str(uuid.UUID(options.run))
    folder = ROOT / 'data' / 'flow-request-acceptance' / run
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'run.json'
    state = json.loads(path.read_text(encoding='utf8')) if path.exists() else {
        'run_id': run, 'server': options.server, 'client_id': options.client_id,
        'project_name': 'VS Request Test ' + datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
        'results': {}, 'receipts': {}, 'downloads': {},
    }
    if state['server'] != options.server:
        raise ValueError('Reuse the original bridge server for this run')
    stage = options.stage
    client = FlowRequestClient(options.server, state.get('client_id'))
    operation, args = arguments(stage, state, options.use_existing_ui_portrait)
    if options.attempt < 1:
        raise ValueError('attempt must be positive')
    request_id = str(uuid.uuid5(uuid.UUID(run), stage if options.attempt == 1 else f'{stage}:attempt:{options.attempt}'))
    previous = state['receipts'].get(stage)
    if previous and previous['id'] != request_id:
        if previous.get('state') not in ('failed', 'blocked'):
            raise ValueError('A new attempt needs an authoritative failed/blocked receipt, never an uncertain or completed submission')
        state.setdefault('receipt_history', {}).setdefault(stage, []).append(previous)
    state['receipts'][stage] = {'id': request_id, 'operation': operation}
    if stage == 'with-reference' and not state['results'].get('portrait', {}).get('images'):
        state['receipts'][stage]['reference_source'] = 'verified_native_ui_portrait_control'
    save(path, state)
    # The bridge deduplicates the stable request ID even if this process dies.
    receipt = client.submit(operation, args, request_id=request_id, confirm_generation=operation == 'generate_image')
    state['client_id'] = receipt['client_id']
    save(path, state)
    try:
        result = client.wait(request_id, timeout=150)
        state['results'][stage] = result
        state['receipts'][stage]['state'] = 'completed'
        save(path, state)
        if operation == 'generate_image' and stage not in state['downloads']:
            state['downloads'][stage] = download_result(folder, stage, result)
            save(path, state)
    except FlowRequestFailure as error:
        state['receipts'][stage].update(state=error.receipt['state'], error=error.receipt.get('result'))
        save(path, state)
        raise
    print(json.dumps({'stage': stage, 'receipt': state['receipts'][stage],
                      'project_id': state['results'].get('project', {}).get('project_id'),
                      'character_id': state['results'].get('character', {}).get('character_id'),
                      'download': state['downloads'].get(stage), 'manifest': str(path)}, ensure_ascii=True))


if __name__ == '__main__':
    main()
