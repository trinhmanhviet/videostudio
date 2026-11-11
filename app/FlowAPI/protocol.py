"""Flow RPC codec. No cookies, browser launch, token generation or network I/O.

Schemas are based on the supplied HAR, not a public/versioned Google API.
"""
from __future__ import annotations

import json
import re
import uuid
from urllib.parse import urlsplit

RPCS = {
    'list_projects': 'UpteDb',
    'list_characters': 'ngNC2',
    'create_project': 'jHPbke',
    'create_character': 'C4BZMd',
    'rename_character': 'rzMKMb',
    'generate_image': 'ogiZ0b',
    'prepare_generation': '__flow_verify__',
}
READ_OPERATIONS = frozenset(('list_projects', 'list_characters'))
MAX_RESPONSE = 2 * 1024 * 1024


class FlowRPCError(ValueError):
    def __init__(self, code, message, *, uncertain=False):
        super().__init__(message)
        self.code = code
        self.uncertain = uncertain


def identifier(value):
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError('ID phải là UUID hợp lệ') from error


def text(value, field, maximum=200):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f'{field} phải có từ 1 đến {maximum} ký tự')
    return value.strip()


def build_command(operation, arguments, request_id):
    """Freeze generation IDs and seed before dispatch; repeating an ID never changes payload."""
    request_id = identifier(request_id)
    if operation not in RPCS or not isinstance(arguments, dict):
        raise ValueError('Thao tác Flow không hợp lệ')
    allowed = {
        'list_projects': set(), 'list_characters': {'project_id'},
        'create_project': {'name'}, 'create_character': {'project_id', 'name'},
        'rename_character': {'project_id', 'character_id', 'name'},
        'generate_image': {'project_id', 'prompt', 'references', 'seed', 'target_character_id'},
        'prepare_generation': {'project_id', 'handoff_hash'},
    }[operation]
    if set(arguments) - allowed:
        raise ValueError('Tham số Flow chưa được hỗ trợ')
    args = dict(arguments)
    project = identifier(args.get('project_id')) if 'project_id' in allowed else None
    if project:
        args['project_id'] = project
    source = f'/project/{project}' if project else '/'
    if operation == 'prepare_generation':
        if not isinstance(args.get('handoff_hash'), str) or not re.fullmatch(r'[0-9a-f]{64}', args['handoff_hash']):
            raise ValueError('Cần khóa bàn giao xác minh dùng một lần')
        payload = []
    elif operation == 'list_projects':
        payload = ['projects/*', 21, None, None, None, None, [1]]
    elif operation == 'list_characters':
        payload = [f'tools/PINHOLE/projects/{project}']
    elif operation == 'create_project':
        args['name'] = text(args.get('name'), 'Tên dự án')
        payload = ['projects/*', [None, [args['name']]], [None, 22]]
    elif operation in ('create_character', 'rename_character'):
        args['name'] = text(args.get('name'), 'Tên nhân vật')
        if operation == 'create_character':
            source += '/character'
            payload = [[project, None, None, [1, args['name'], []]]]
        else:
            args['character_id'] = identifier(args.get('character_id'))
            source += '/character/' + args['character_id']
            payload = [[project, args['character_id'], None, [1, args['name']]],
                       [['entity_info.display_name']]]
    else:
        args['prompt'] = text(args.get('prompt'), 'Prompt', 30000)
        refs = args.get('references', [])
        if not isinstance(refs, list):
            raise ValueError('references phải là danh sách')
        normalized = []
        for ref in refs:
            if not isinstance(ref, dict) or set(ref) != {'character_id', 'name'}:
                raise ValueError('Mỗi tham chiếu cần character_id và name')
            normalized.append({'character_id': identifier(ref['character_id']),
                               'name': text(ref['name'], 'Tên tham chiếu')})
        if len({ref['character_id'] for ref in normalized}) != len(normalized):
            raise ValueError('Tham chiếu bị trùng ID')
        args['references'] = normalized
        namespace = uuid.UUID(request_id)
        seed = args.get('seed', namespace.int % (2**31))
        if type(seed) is not int or not 0 <= seed < 2**31:
            raise ValueError('seed phải là số nguyên từ 0 đến 2147483647')
        args['seed'] = seed
        context = [None, 22, None, None, None, project, None, None, None, None, []]
        parts = []
        for ref in normalized:
            if parts:
                parts.append([' '])
            parts.append([None, [None, None, [ref['character_id'], ref['name']]]])
        parts.append([(' ' if normalized else '') + args['prompt']])
        mode = 2
        if args.get('target_character_id'):
            args['target_character_id'] = identifier(args['target_character_id'])
            source += '/character/' + args['target_character_id']
            mode = 3
        request = [None, None, None, seed, mode, 'BELUGA', None, context,
                   [parts], None, [[ref['character_id']] for ref in normalized] or None,
                   None, str(uuid.uuid5(namespace, 'generation')).upper(),
                   str(uuid.uuid5(namespace, 'client')).upper()]
        batch = [str(uuid.uuid5(namespace, 'batch')).upper()]
        if mode == 3:
            # HAR: mode alone is insufficient. This binds the generated portrait
            # to its existing Character, rather than producing an unassigned image.
            batch.extend([None, [args['target_character_id'], [0]]])
        payload = [None, [request], 1, context, batch]
    return {'id': request_id, 'operation': operation, 'arguments': args,
            'rpcid': RPCS[operation], 'source_path': source, 'payload': payload}


def parse_response(body, rpcid, http_status=200):
    if not isinstance(body, str) or len(body.encode('utf8')) > MAX_RESPONSE:
        raise FlowRPCError('invalid_response', 'Phản hồi Flow quá lớn hoặc không hợp lệ', uncertain=True)
    if http_status in (401, 403):
        raise FlowRPCError('authentication_required', 'Flow từ chối phiên đăng nhập; kiểm tra tab Flow')
    if http_status == 429:
        raise FlowRPCError('rate_limited', 'Flow đang giới hạn request; không tự gửi lại')
    if http_status != 200:
        raise FlowRPCError('http_error', f'Flow trả HTTP {http_status}', uncertain=True)
    body = body.strip().removeprefix(")]}'")
    matches = []
    for line in body.splitlines():
        try:
            frame = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(frame, list):
            continue
        for item in frame:
            if isinstance(item, list) and len(item) >= 3 and item[:2] == ['wrb.fr', rpcid]:
                matches.append(item)
    if len(matches) != 1:
        raise FlowRPCError('rpc_response_missing', 'Không có đúng một phản hồi khớp RPC', uncertain=True)
    frame = matches[0]
    if len(frame) > 5 and frame[5] is not None:
        detail = json.dumps(frame[5])
        codes = re.findall(r'PUBLIC_ERROR_[A-Z_]+', detail)
        code = codes[0] if codes else 'rpc_rejected'
        raise FlowRPCError(code, 'Flow từ chối request: ' + code)
    try:
        payload = json.loads(frame[2])
    except (ValueError, TypeError) as error:
        raise FlowRPCError('invalid_payload', 'Phản hồi RPC không phải JSON hợp lệ', uncertain=True) from error
    if payload is None:
        raise FlowRPCError('empty_payload', 'Flow chưa trả kết quả có thể xác nhận', uncertain=True)
    return payload


def decode_result(operation, payload):
    """Use known response positions, never choose a result by display order or partial prompt."""
    try:
        if operation == 'create_project':
            return {'project_id': identifier(payload[0]), 'name': text(payload[1][0], 'Tên dự án')}
        if operation == 'list_projects':
            return {'projects': [{'project_id': identifier(row[0]), 'name': text(row[1][0], 'Tên dự án')}
                                 for row in payload[0]]}
        if operation == 'create_character':
            character = payload[0]
            return {'project_id': identifier(character[0]), 'character_id': identifier(character[1]),
                    'name': text(character[3][1], 'Tên nhân vật')}
        if operation in ('rename_character', 'list_characters'):
            # Retain the returned project/entity structure for reconciliation, not a fake success flag.
            return {'data': payload}
        if operation == 'generate_image':
            images = []
            for media in payload[0]:
                info = media[6]
                data = info[0]
                url = data[13]
                parsed = urlsplit(url)
                if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                    raise ValueError('Invalid image URL')
                width, height = info[2][:2]
                if type(width) is not int or type(height) is not int or min(width, height) <= 0:
                    raise ValueError('Invalid dimensions')
                images.append({'image_id': identifier(media[0]), 'prompt': data[7], 'url': url,
                               'width': width, 'height': height})
            if len(images) != 1:
                raise ValueError('Expected one image')
            return {'images': images}
    except (IndexError, KeyError, TypeError, ValueError) as error:
        raise FlowRPCError('schema_mismatch', 'Cấu trúc kết quả Flow đã khác; giữ request để đối chiếu', uncertain=True) from error
    raise FlowRPCError('unsupported_operation', 'Thao tác không hỗ trợ')
