"""Where finished videos are saved (Cài đặt → Nơi lưu video).

The chosen folder is kept in DATA_ROOT/output-root.json. New videos go to <folder>\\<project>\\...; videos made
earlier stay where they are and remain owned (their roots are remembered), so changing the folder never moves or
orphans existing work.
"""
from __future__ import annotations

import json
import os
import shutil
import string
import uuid
from pathlib import Path

from .paths import APP_ROOT, DATA_ROOT

SETTINGS = DATA_ROOT / 'output-root.json'
DEFAULT = os.getenv('VS_OUTPUT_DIR', 'E:/Videos')


def _read():
    try:
        value = json.loads(SETTINGS.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def configured_root():
    """The folder for new videos: the one chosen in Settings, else VS_OUTPUT_DIR, else E:/Videos."""
    root = _read().get('root')
    return Path(root) if isinstance(root, str) and root else Path(DEFAULT)


def previous_roots():
    return [Path(p) for p in _read().get('previous', []) if isinstance(p, str)]


def validate(path):
    if not isinstance(path, str) or not path.strip():
        raise ValueError('Nhập đường dẫn thư mục, ví dụ D:\\Videos')
    folder = Path(path.strip().strip('"'))
    if not folder.is_absolute() or not folder.drive:
        raise ValueError('Cần đường dẫn đầy đủ có ổ đĩa, ví dụ D:\\Videos')
    if folder.parent == folder:
        raise ValueError('Chọn một thư mục bên trong ổ đĩa (ví dụ D:\\Videos), không dùng thẳng gốc ổ')
    resolved = folder.resolve()
    for forbidden in (APP_ROOT.resolve(), DATA_ROOT.resolve()):
        if resolved == forbidden or resolved.is_relative_to(forbidden) or forbidden.is_relative_to(resolved):
            raise ValueError('Không lưu video vào thư mục mã nguồn hoặc dữ liệu của tool')
    if folder.exists() and not folder.is_dir():
        raise ValueError('Đường dẫn này là một tệp, không phải thư mục')
    folder.mkdir(parents=True, exist_ok=True)
    probe = folder / f'.videostudio-write-test-{uuid.uuid4().hex}'
    try:
        probe.write_bytes(b'ok')
    except OSError as error:
        raise ValueError(f'Không ghi được vào thư mục này: {error}')
    finally:
        probe.unlink(missing_ok=True)
    return folder


def save(store, path):
    """Switch new videos to `path`. The previous folder is remembered so its videos stay listed and removable."""
    folder = validate(path)
    current = Path(store.outputs)
    data = _read()
    previous = [p for p in data.get('previous', []) if Path(p).resolve() != folder.resolve()]
    if current.resolve() != folder.resolve() and str(current) not in previous:
        previous.append(str(current))
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    part = SETTINGS.with_suffix('.part')
    part.write_text(json.dumps({'root': str(folder), 'previous': previous}, ensure_ascii=False, indent=1), encoding='utf-8')
    part.replace(SETTINGS)
    store.outputs = folder
    return describe(store)


def drives():
    result = []
    for letter in string.ascii_uppercase:
        root = Path(f'{letter}:/')
        try:
            if root.exists():
                usage = shutil.disk_usage(root)
                result.append({'drive': f'{letter}:', 'free_gb': round(usage.free / 2**30, 1), 'total_gb': round(usage.total / 2**30, 1)})
        except OSError:
            continue
    return result


def describe(store):
    root = Path(store.outputs)
    try:
        usage = shutil.disk_usage(root if root.exists() else root.anchor)
        free, total = round(usage.free / 2**30, 1), round(usage.total / 2**30, 1)
    except OSError:
        free = total = None
    return {'root': str(root), 'free_gb': free, 'total_gb': total, 'default': DEFAULT,
            'previous': [str(p) for p in previous_roots()], 'drives': drives()}
