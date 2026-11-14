"""Read-only scene progress. Partial cache previews never become stage checkpoints.

Only owned output files with matching hashes and current scene receipts are shown.
Editing/export remains exclusively in the existing scene editor APIs.
"""
import hashlib
import io
import json
import warnings
from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException
from fastapi.responses import Response, FileResponse
from PIL import Image

from .project_lifecycle import deleted_job_ids, reject_retired_job
from .core import digest

MAX_IMAGE_BYTES = 20 * 1024 * 1024


def _alias(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


class JobDetails:
    def __init__(self, store):
        self.store = store

    def _job(self, jid):
        with self.store.db() as c:
            reject_retired_job(c, jid)
            if jid in deleted_job_ids(c): raise ValueError('Video no longer available')
        job = self.store.get(jid)
        raw = Path(job['output'])
        root = raw.resolve()
        outputs = self.store.root_containing(raw) or self.store.outputs.resolve()
        if not raw.is_absolute() or root == outputs or not root.is_relative_to(outputs):
            raise ValueError('Output is outside the owned output directory')
        if any(_alias(p) for p in (raw, *raw.parents)):
            raise ValueError('Output aliases are not supported')
        with self.store.db() as c:
            for row in c.execute('SELECT id,output FROM jobs WHERE id<>?', (jid,)):
                other = Path(row['output']).resolve()
                if root == other or root.is_relative_to(other) or other.is_relative_to(root):
                    raise ValueError('Output ownership is ambiguous')
        return job, root

    @staticmethod
    def _scenes(job):
        speech = job.get('checkpoints', {}).get('speech', {})
        scenes = speech.get('scenes')
        if not scenes:
            groups = {}
            for index, utterance in enumerate(speech.get('utterances', [])):
                key = utterance.get('scene_index', index)
                groups.setdefault(key, []).append(utterance)
            scenes = []
            for items in groups.values():
                start = items[0].get('start', 0)
                end = items[-1].get('end', start)
                scenes.append(dict(items[0], narration=' '.join(str(u.get('narration', '')) for u in items),
                                   start=start, end=end, duration=end-start))
        return [{'index': i, 'scene_id': str(s.get('scene_id') or f'scene-{i:04}'),
                 'narration': str(s.get('narration', '')), 'visual_prompt': str(s.get('visual_prompt', '')),
                 'start': s.get('start', 0), 'end': s.get('end', s.get('start', 0) + s.get('duration', 0)),
                 'duration': s.get('duration', 0)} for i, s in enumerate(scenes or [])]

    @staticmethod
    def _owned(path, root):
        raw = Path(path)
        resolved = raw.resolve()
        if not resolved.is_relative_to(root) or resolved == root or any(_alias(p) for p in (raw, *raw.parents)):
            raise ValueError('File is outside the owned output directory')
        return resolved

    def _image(self, job, root, index, scenes):
        if type(index) is not int or not 0 <= index < len(scenes): raise ValueError('Scene not found')
        scene = scenes[index]
        images = job.get('checkpoints', {}).get('images')
        provider = job['request'].get('image_provider', 'comfy')
        if images is not None:
            rows = images.get('scenes', [])
            if index >= len(rows): raise ValueError('Image not available')
            expected = Path(rows[index]['path']).resolve()
            asset_index = next((i for i, a in enumerate(images.get('assets', [])) if Path(a['path']).resolve() == expected), None)
            if asset_index is None: raise ValueError('Original image is not checkpoint-attested')
            path, _ = self._asset(job, root, 'images', asset_index, verify=False, allow_image=True)
            sha = images['assets'][asset_index].get('sha256')
            provider = rows[index].get('image_provider', images.get('image_provider', provider))
        else:
            path = self._owned(root / f'images-{index:04}.png', root)
            receipt = self._owned(path.with_suffix('.checkpoint.json'), root)
            if not receipt.is_file() or receipt.stat().st_size > 1024 * 1024: raise ValueError('Image receipt missing')
            saved = json.loads(receipt.read_text(encoding='utf-8'))
            if saved.get('prompt') != scene['visual_prompt']: raise ValueError('Image receipt belongs to another prompt')
            # Mixed Flow fallback images remain visible with their actual provider.
            provider = saved.get('provider', 'comfy')
            sha = saved.get('sha256')
        if not path.is_file() or not 0 < path.stat().st_size <= MAX_IMAGE_BYTES: raise ValueError('Image not available')
        raw = path.read_bytes()
        if not isinstance(sha, str) or hashlib.sha256(raw).hexdigest() != sha: raise ValueError('Image bytes changed')
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as picture:
                if picture.format != 'PNG' or getattr(picture, 'n_frames', 1) != 1 or min(picture.size) < 32 or picture.width * picture.height > 20_000_000:
                    raise ValueError('Invalid scene image')
                picture.load()
        return path, raw, provider

    def image(self, jid, index):
        job, root = self._job(jid)
        return self._image(job, root, index, self._scenes(job))[0]

    def image_bytes(self, jid, index):
        job, root = self._job(jid)
        return self._image(job, root, index, self._scenes(job))[1]

    def _asset(self, job, root, stage, index, verify=True, allow_image=False):
        if stage not in ('script', 'speech', 'music', 'subtitles') and not (allow_image and stage=='images'): raise ValueError('Asset not available')
        assets = job.get('checkpoints', {}).get(stage, {}).get('assets', [])
        if type(index) is not int or not 0 <= index < len(assets): raise ValueError('Asset not available')
        entry = assets[index]
        try:
            path = self._owned(entry['path'], root)
        except ValueError:
            # Derived exports retain attested parent audio/subtitles. Permit
            # only a matching asset owned by another recorded job, never an
            # arbitrary path supplied by this checkpoint.
            path = self._owned(entry['path'], self.store.root_containing(entry['path']) or self.store.outputs.resolve())
            proven = False
            with self.store.db() as db:
                for row in db.execute('SELECT c.value,j.output FROM checkpoints c JOIN jobs j ON j.id=c.job WHERE c.stage=?', (stage,)):
                    source_root = Path(row['output']).resolve()
                    if not path.is_relative_to(source_root): continue
                    for source in json.loads(row['value']).get('assets', []):
                        if Path(source.get('path', '')).resolve() == path and source.get('sha256') == entry.get('sha256'):
                            proven = True; break
                    if proven: break
            if not proven: raise ValueError('Shared source is not checkpoint-attested by its owner')
        if not path.is_file(): raise ValueError('Asset not available')
        if verify and digest(path) != entry.get('sha256'): raise ValueError('Asset bytes changed')
        return path, None

    def snapshot(self, jid):
        job, root = self._job(jid)
        meme = job['request'].get('workflow_mode') == 'meme'
        scenes = [] if meme else self._scenes(job)
        prefix = '/api/jobs/' + quote(jid, safe='') + '/details'
        for scene in scenes:
            scene.update(image_url=None, image_provider=None, image_status='missing')
            try:
                _, _, provider = self._image(job, root, scene['index'], scenes)
                scene.update(image_url=f'{prefix}/images/{scene["index"]}', image_provider=provider, image_status='ready')
            except (ValueError, OSError, KeyError, TypeError, Image.DecompressionBombError, Image.DecompressionBombWarning):
                pass
        media = {}
        for stage in ('script', 'speech', 'music', 'subtitles'):
            media[stage] = []
            for index, _ in enumerate(job.get('checkpoints', {}).get(stage, {}).get('assets', [])):
                try:
                    path, _ = self._asset(job, root, stage, index, verify=False)
                    if path.suffix.lower() not in ('.wav', '.mp3', '.m4a', '.srt', '.ass', '.vtt', '.txt', '.json'): continue
                    media[stage].append({'name': path.name, 'url': f'{prefix}/assets/{stage}/{index}', 'kind': path.suffix.lower()[1:]})
                except (ValueError, OSError, KeyError, TypeError):
                    pass
        partial = 'images' not in job.get('checkpoints', {})
        return {'job_id': jid, 'scenes': scenes, 'image_count': sum(bool(s['image_url']) for s in scenes),
                'partial': partial, 'editable': False, 'media': media,
                'editor_url': '/meme-editor?job=' + quote(jid, safe='') if meme else None,
                'unavailable_reason': 'Hoàn tất bước lời đọc và hình ảnh trước khi sửa từng cảnh. Tiếp tục tác vụ sẽ xử lý các ảnh còn thiếu; không chỉ riêng cảnh đang chọn.' if partial and not meme else None}


def register_job_details_routes(app, store, scene_editor=None, same_origin=None):
    """Register additive GET-only routes; the editor argument is integration-compatible."""
    service = JobDetails(store)

    def call(fn, *args):
        try: return fn(*args)
        except KeyError: raise HTTPException(404, 'Job or asset not found')
        except (ValueError, OSError, TypeError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise HTTPException(404, 'Job or verified asset not available')

    @app.get('/api/jobs/{job_id}/details')
    def details(job_id: str):
        return call(service.snapshot, job_id)

    @app.get('/api/jobs/{job_id}/details/images/{index}')
    def image(job_id: str, index: int):
        return Response(call(service.image_bytes, job_id, index), media_type='image/png', headers={'Cache-Control': 'no-store'})

    @app.get('/api/jobs/{job_id}/details/assets/{stage}/{index}')
    def asset(job_id: str, stage: str, index: int):
        def read():
            job, root = service._job(job_id)
            return service._asset(job, root, stage, index)
        path, _ = call(read)
        types = {'.wav': 'audio/wav', '.mp3': 'audio/mpeg', '.m4a': 'audio/mp4', '.json': 'application/json'}
        return FileResponse(path, media_type=types.get(path.suffix.lower(), 'text/plain; charset=utf-8'), filename=path.name, headers={'Cache-Control': 'no-store'})

    return service
