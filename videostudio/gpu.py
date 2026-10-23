"""Account only attested VideoStudio-owned Comfy allocations, never call /free.
A foreign/unknown prompt after the attested baseline revokes reclaim accounting.
Comfy's normal serialized loader may offload its own idle models; this module
never unloads a foreign model, kills a process or interrupts the queue.
"""
import json,threading
from pathlib import Path
_LOCK=threading.Lock()
def record_owned(path,prompt_id):
    path=Path(path)
    with _LOCK:
        if not path.is_file():return  # no unearned ownership baseline
        d=json.loads(path.read_text());ids=d.setdefault('prompt_ids',[])
        if prompt_id not in ids:ids.append(prompt_id)
        tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(d));tmp.replace(path)
def headroom(client,devices,path):
    free=min((d.get('vram_free',0) for d in devices),default=0)
    path=Path(path)
    if not path.is_file():return free,False
    try:
        record=json.loads(path.read_text())
        if record.get('baseline_attested_empty_gpu') is not True:return free,False
        response=client.get('history',params={'max_items':1000});response.raise_for_status();history=response.json()
        known=set(record['prompt_ids']);baseline=record['baseline_order'];found=False
        for pid,entry in history.items():
            order=entry['prompt'][0]
            if order==baseline:found=True
            if order>=baseline and pid not in known:return free,False
        if not found:return free,False
        # torch_vram_total excludes foreign processes (e.g. local LLM Vulkan).
        reusable=min(d.get('vram_free',0)+d.get('torch_vram_total',0) for d in devices)
        return reusable,True
    except (OSError,ValueError,KeyError,TypeError):return free,False
