"""One-time cold-service recovery after an attested native process death.
Never infer 'not sent' from connection failure. Keep the accepted old prompt ID,
verify no history/queue/output exists, and journal the distinct recovery attempt.
"""
import hashlib,json,time,uuid
from pathlib import Path

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def resolve_music_kind(output):
    root=Path(output);journal=root/'music-crash-recovery.json'
    if not journal.is_file():return 'music'
    d=json.loads(journal.read_text(encoding='utf8'));receipt=root/'music-receipt.json';evidence=root/'comfy-crash-evidence.json'
    if d.get('replacement_kind')!='music-crash-recovery-01':raise ValueError('Invalid bounded recovery kind')
    if digest(receipt)!=d.get('original_receipt_sha256') or digest(evidence)!=d.get('evidence_sha256'):raise ValueError('Recovery evidence/receipt changed')
    if json.loads(receipt.read_text())['prompt_id']!=d.get('old_prompt_id'):raise ValueError('Recovery prompt correlation mismatch')
    return d['replacement_kind']

def prepare_music_recovery(output,client,comfy_output,job_id):
    root=Path(output);journal=root/'music-crash-recovery.json'
    if journal.is_file():return {'kind':resolve_music_kind(root),'created':False}
    receipt=root/'music-receipt.json';evidence=root/'comfy-crash-evidence.json'
    old=json.loads(receipt.read_text())['prompt_id'];uuid.UUID(old)
    ev=json.loads(evidence.read_text(encoding='utf8'))
    if ev.get('old_prompt_id')!=old or ev.get('old_process_absent') is not True or ev.get('exception_code')!='0xc0000005' or ev.get('faulting_module')!='torch_cpu.dll':raise ValueError('Native crash evidence is insufficient')
    r=client.get('history/'+old);r.raise_for_status()
    response=r.json()
    if not isinstance(response,dict):raise ValueError('Invalid history response')
    if old in response:raise ValueError('Old request still has history; recover it, do not regenerate')
    r=client.get('queue');r.raise_for_status();queue=r.json()
    if not isinstance(queue.get('queue_running'),list) or not isinstance(queue.get('queue_pending'),list) or queue['queue_running'] or queue['queue_pending']:raise ValueError('Comfy queue is not provably empty; recovery preparation refused')
    if not Path(comfy_output).is_dir():raise ValueError('Comfy output directory unavailable; cannot establish absence of saved output')
    candidates=list((Path(comfy_output)/'videostudio').glob(job_id+'-music_*.mp3'))
    if (root/'music.mp3').is_file() or candidates:raise ValueError('Music artifact exists; inspect/recover before regenerating')
    history=root/'receipts';history.mkdir(exist_ok=True);archived=history/('music-original-'+old+'.json')
    if archived.exists() and archived.read_bytes()!=receipt.read_bytes():raise ValueError('Archived receipt mismatch')
    if not archived.exists():archived.write_bytes(receipt.read_bytes())
    d={'old_prompt_id':old,'replacement_kind':'music-crash-recovery-01','original_receipt_sha256':digest(receipt),'evidence_sha256':digest(evidence),'original_receipt_preserved':str(archived),'reason':'Native Comfy process died; fresh service has no old history, queue or saved music output','created':time.time(),'max_recovery_attempts':1}
    temp=journal.with_suffix('.part.json');temp.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(journal)
    return {'kind':d['replacement_kind'],'created':True}
