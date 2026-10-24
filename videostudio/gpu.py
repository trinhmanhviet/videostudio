"""GPU and VRAM management for VideoStudio.
Coordinates sequential execution on GPU:
1. VieNeu speech synthesis -> release VRAM
2. ComfyUI Qwen Image 2.1 scene generation -> release VRAM (/free)
3. ComfyUI Stable Audio 3 music generation -> release VRAM (/free)
4. FFmpeg assembly and export
"""
import json
import time
import threading
from pathlib import Path

_LOCK = threading.Lock()

def record_owned(path, prompt_id):
    path = Path(path)
    with _LOCK:
        if not path.is_file():
            return  # no unearned ownership baseline
        d = json.loads(path.read_text())
        ids = d.setdefault('prompt_ids', [])
        if prompt_id not in ids:
            ids.append(prompt_id)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(d))
        tmp.replace(path)

def free_comfy(client):
    """ComfyUI native model management handles model swapping safely in process memory.
    Avoid calling POST /free which triggers an unsafe c10.dll access violation (0xc0000005) in PyTorch allocator."""
    return True

def headroom(client, devices, path):
    free = min((d.get('vram_free', 0) for d in devices), default=0)
    path = Path(path)
    if not path.is_file():
        return free, False
    try:
        record = json.loads(path.read_text())
        if record.get('baseline_attested_empty_gpu') is not True:
            return free, False
        response = client.get('history', params={'max_items': 1000})
        response.raise_for_status()
        history = response.json()
        known = set(record['prompt_ids'])
        baseline = record['baseline_order']
        found = False
        for pid, entry in history.items():
            order = entry['prompt'][0]
            if order == baseline:
                found = True
            if order >= baseline and pid not in known:
                return free, False
        if not found:
            return free, False
        # torch_vram_total excludes foreign processes (e.g. local LLM Vulkan).
        reusable = min(d.get('vram_free', 0) + d.get('torch_vram_total', 0) for d in devices)
        return reusable, True
    except (OSError, ValueError, KeyError, TypeError):
        return free, False
