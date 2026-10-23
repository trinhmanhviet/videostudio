"""Read-only StoryForge import; never infer clone IDs from sample filenames.
StoryForge services/voice_samples.py: clone IDs are 'clone:'+Asset.id, not a
sample's storage filename. A complete DB export must include every voice-sample
asset (all projects/statuses) and resolved local reference paths; DB is never started.
Optional VS_VOICES_EXPORT: JSON {complete: true, voices:[{id,name,kind,
reference_path?,sample_path?,sha256?}]}. Existing entries are never dropped.
"""
import json, os
from pathlib import Path
from .core import digest

class Voices:
    def __init__(self,root,export=None): self.root=Path(root); self.export=Path(export) if export else None
    def catalog(self):
        rows={}; warnings=[]; complete=False
        # Historical requests recover known preset/clone identities without trusting
        # incomplete metadata as an authoritative complete voice inventory.
        base=self.root/'Voices'/'Work'/'Previews'
        if base.exists():
            for p in base.glob('*/request.json'):
                try:
                    d=json.loads(p.read_text(encoding='utf-8')); v=d.get('voice_id')
                    if not v: continue
                    r=rows.setdefault(v,{'id':v,'name':v,'kind':'clone' if v.startswith('clone:') else 'preset','source':'historical_request'})
                    if (p.parent/'preview.wav').is_file():r['sample_path']=str(p.parent/'preview.wav')
                    ref=d.get('voice_reference')
                    if isinstance(ref,dict) and ref.get('path'):r['reference_path']=ref['path'];r['sha256']=ref.get('sha256')
                except (OSError,ValueError):warnings.append('Unreadable historical request: '+str(p))
        if self.export and self.export.is_file():
            d=json.loads(self.export.read_text(encoding='utf-8'))
            for r in d['voices']:
                if not isinstance(r.get('id'),str) or r.get('kind') not in ('preset','clone'):raise ValueError('Invalid voice export')
                rows[r['id']]={**rows.get(r['id'],{}),**r,'source':'read_only_export'}
            complete=d.get('complete') is True
        if not complete:warnings.append('Voice inventory incomplete: stopped StoryForge DB not queried. Supply complete read-only asset/preset export; no clone is silently omitted or fabricated.')
        for r in rows.values():
            if r['kind']=='clone':
                p=Path(r.get('reference_path','__missing__'))
                r['available']=p.is_file() and bool(r.get('sha256')) and digest(p)==r['sha256']
            else:r['available']=True
            if r.get('status') and r['status']!='locked':r['available']=False
            if r.get('selectable') is False:r['available']=False
        # Loose samples are retained as inventory, NOT falsely advertised as cloned IDs.
        samples=[str(p) for p in (self.root/'Voices'/'Samples').glob('*') if p.is_file()]
        return {'voices':sorted(rows.values(),key=lambda r:r['id']),'complete':complete,'warnings':warnings,'unmapped_sample_files':samples}
    def selected(self,vid):
        for v in self.catalog()['voices']:
            if v['id']==vid:
                if not v['available']:raise ValueError('Clone reference unavailable or checksum unverified')
                return v
        raise ValueError('Unknown voice; import catalog first')
