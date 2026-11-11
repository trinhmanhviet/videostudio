"""Scene-scoped visual contracts and artifact-bound review protocol.
No model calls, GPU operations or implicit approval. A reviewer transport must be
supplied explicitly; syntactic validity is never evidence of visual correctness.
"""
import copy,hashlib,hmac,json,os,re,time,unicodedata
from pathlib import Path
from .core import PermanentError,digest,Cancelled

INTENTS={'reconstruction','contemporary','museum','comparison','diagram','metaphor','fiction'}
VERSION=1

def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf8')).hexdigest()

def text_hash(text):
    return fingerprint(' '.join(unicodedata.normalize('NFC',text).split()))

def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.part');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8');tmp.replace(path)

def bind_scene_ids(scenes):
    result=[];seen=set()
    for scene in scenes:
        d=copy.deepcopy(scene);identifier=d.get('scene_id') or 's-'+text_hash(d.get('narration',''))[:24]
        if not isinstance(identifier,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',identifier):raise ValueError('Invalid scene_id')
        if identifier in seen:raise ValueError('Duplicate narration needs explicit unique scene_id')
        seen.add(identifier);d['scene_id']=identifier;result.append(d)
    return result

def strings(value,name,maximum=40):
    if not isinstance(value,list) or len(value)>maximum or any(not isinstance(s,str) or not s.strip() or len(s)>1000 for s in value):raise ValueError('Invalid '+name)
    return value

def validate_contract(c):
    if not isinstance(c,dict) or c.get('intent') not in INTENTS:raise ValueError('Invalid visual intent')
    if not isinstance(c.get('scene_id'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',c['scene_id']):raise ValueError('Invalid scene_id')
    context=c.get('context')
    if not isinstance(context,dict) or set(context)-{'era','region','setting','species','mechanism','world'}:raise ValueError('Invalid scene context')
    if any(not isinstance(v,str) or len(v)>1000 for v in context.values()):raise ValueError('Invalid scene context text')
    if not strings(c.get('must_show'), 'must_show'):raise ValueError('Explicit must_show is required')
    strings(c.get('avoid'), 'avoid')
    if type(c.get('separate_subjects',False)) is not bool:raise ValueError('Invalid separation flag')
    if c['intent']=='comparison' and c.get('separate_subjects') is not True:raise ValueError('Comparison requires separate subjects/panels')
    refs=c.get('references',[])
    if not isinstance(refs,list) or len(refs)>20:raise ValueError('Invalid references')
    for r in refs:
        if not isinstance(r,dict) or not isinstance(r.get('path'),str) or not re.fullmatch(r'[a-f0-9]{64}',r.get('sha256','')):raise ValueError('Invalid reference binding')
        if not Path(r['path']).is_file() or digest(r['path'])!=r['sha256']:raise ValueError('Reference missing or changed')
    # Contradictory positive/negative specs must be resolved, not appended together.
    for required in c['must_show']:
        if any(contains(required,term) for term in c['avoid']):raise ValueError('Contradictory visual constraints')
    return c

def contains(text,phrase):
    return bool(re.search(r'(?<!\w)'+re.escape(' '.join(phrase.casefold().split()))+r'(?!\w)',' '.join(text.casefold().split())))

def prompt_issues(prompt,c):
    validate_contract(c)
    if not isinstance(prompt,str) or not prompt.strip():return ['Empty visual prompt']
    # Conservative lint, NOT a semantic classifier: negated mentions need explicit rewrite.
    return ['Prompt includes scene-prohibited object: '+term for term in c['avoid'] if contains(prompt,term)]

def compile_prompt(prompt,project,c):
    validate_contract(c)
    if not isinstance(project,dict) or project.get('schema_version')!=VERSION:raise ValueError('Invalid visual project schema')
    if set(project)-{'schema_version','style','identities'}:raise ValueError('Global era/objects not supported; use scene context')
    style=project.get('style','')
    if not isinstance(style,str) or len(style)>2000:raise ValueError('Invalid project style')
    identities=strings(project.get('identities',[]),'identities')
    issues=prompt_issues(prompt,c)
    if issues:raise ValueError('; '.join(issues))
    context='; '.join(k+': '+v for k,v in c['context'].items() if v)
    positive=' | '.join(s for s in [prompt,'Scene intent: '+c['intent'],context,'Required visible content: '+ '; '.join(c['must_show']),style,'; '.join(identities)] if s)
    if c['intent']=='comparison':positive+=' | Show subjects in separate panels or shots; do not fuse garments, bodies, or objects.'
    effective_issues=prompt_issues(positive,c)
    if effective_issues:raise ValueError('; '.join(effective_issues))
    return {'positive':positive,'negative':', '.join(['blur','watermark','distorted anatomy','text']+c['avoid'])}

def conditioning_key(positive,negative,c,workflow):
    validate_contract(c)
    return fingerprint({'version':VERSION,'positive':positive,'negative':negative,'contract':c,'workflow':workflow})

def receipt_signature(value):
    secret=os.getenv('VS_VISUAL_REVIEW_SECRET','')
    if len(secret)<32:return None
    payload={k:v for k,v in value.items() if k!='signature'}
    return hmac.new(secret.encode('utf8'),fingerprint(payload).encode('ascii'),hashlib.sha256).hexdigest()

def review_image(path,c,key,reviewer,check):
    validate_contract(c);check();before=digest(path)
    result={'schema_version':VERSION,'scene_id':c['scene_id'],'image_sha256':before,'contract_sha256':fingerprint(c),'conditioning_key':key,'status':'needs_review','reviewer':'unavailable','observations':[],'issues':[],'uncertain':True,'reviewed_at':time.time()}
    if reviewer is None:
        result['issues']=['No image-review transport configured'];return result
    try:
        raw=reviewer(str(path),copy.deepcopy(c),check)
        check()
        valid=(isinstance(raw,dict) and raw.get('status') in ('pass','fail','needs_review') and type(raw.get('uncertain')) is bool and isinstance(raw.get('reviewer'),str) and bool(raw['reviewer'].strip()))
        if valid:
            strings(raw.get('observations'),'observations');strings(raw.get('issues'),'issues')
            valid=bool(raw['observations'])
        if not valid:raise ValueError('Malformed image-review result')
        result.update({k:raw[k] for k in ('status','reviewer','observations','issues','uncertain')})
        if result['uncertain'] or (result['status']=='pass' and result['issues']) or (result['status']=='fail' and not result['issues']):result['status']='needs_review'
        if digest(path)!=before:raise ValueError('Image changed during review')
    except Cancelled:raise
    except Exception as e:
        result.update(status='needs_review',uncertain=True,issues=[type(e).__name__+': '+str(e)[:300]])
    if receipt_signature(result) is None:
        result.update(status='needs_review',uncertain=True,issues=['No local receipt-signing secret configured'])
    else:result['signature']=receipt_signature(result)
    return result

def receipt_passes(r,path,c,key):
    try:
        validate_contract(c)
        if not isinstance(r,dict):return False
        signature=receipt_signature(r)
        if not signature or not isinstance(r.get('signature'),str) or not hmac.compare_digest(signature,r['signature']):return False
        return (isinstance(r,dict) and r.get('schema_version')==VERSION and r.get('status')=='pass' and r.get('uncertain') is False and r.get('scene_id')==c['scene_id'] and r.get('image_sha256')==digest(path) and r.get('contract_sha256')==fingerprint(c) and r.get('conditioning_key')==key and isinstance(r.get('reviewer'),str) and bool(r['reviewer'].strip()) and bool(strings(r.get('observations'),'observations')) and strings(r.get('issues'),'issues')==[])
    except (OSError,ValueError,TypeError,KeyError):return False

def gate_mode(j=None):
    # Persist required policy in checkpoints so a later environment change cannot downgrade it.
    pinned=bool(j and j.get('checkpoints',{}).get('images',{}).get('visual_qa_required'))
    if j:
        policy=Path(j['output'])/'visual-policy.json'
        if policy.is_file():
            try:
                d=json.loads(policy.read_text(encoding='utf8'))
                if d!={'schema_version':VERSION,'job_id':j['id'],'mode':'required'}:raise ValueError('Policy mismatch')
                pinned=True
            except (OSError,ValueError,TypeError) as e:raise PermanentError('Visual quality: invalid persisted policy') from e
    mode=os.getenv('VS_VISUAL_QA','legacy')
    if mode not in ('legacy','required'):raise PermanentError('Visual quality: invalid VS_VISUAL_QA mode')
    # User-facing quick/careful use technical/manual review; autonomous required
    # remains a distinct opt-in integration. Existing required policy cannot downgrade.
    if j and j.get('request',{}).get('quality_mode') in ('quick','careful'):mode='legacy'
    return 'required' if pinned else mode

def load_contracts(j):
    path=Path(j['output'])/'visual-contracts.json'
    try:
        d=json.loads(path.read_text(encoding='utf8'))
        if not isinstance(d,dict) or type(d.get('schema_version')) is not int or d.get('schema_version')!=VERSION or d.get('job_id')!=j['id']:raise ValueError('Contract job/schema mismatch')
        scene_rows=bind_scene_ids(j['checkpoints']['speech']['utterances'])
        if not scene_rows:raise ValueError('Empty scene set is not reviewable')
        if not isinstance(d.get('scenes'),list):raise ValueError('Contract scene list required')
        mapped={}
        for c in d['scenes']:
            validate_contract(c)
            if c['scene_id'] in mapped:raise ValueError('Duplicate scene contract')
            mapped[c['scene_id']]=c
        if set(mapped)!={s['scene_id'] for s in scene_rows}:raise ValueError('Final scenes and contracts do not match')
        for s in scene_rows:
            c=mapped[s['scene_id']]
            if c.get('narration_sha256')!=text_hash(s['narration']):raise ValueError('Contract narration changed')
            compile_prompt(s['visual_prompt'],d['project'],c)
        return d,scene_rows,mapped,path
    except (OSError,ValueError,TypeError,KeyError) as e:
        raise PermanentError('Visual quality: contracts missing/invalid; '+str(e)[:300]) from e

def require_release(j,workflow_factory):
    if gate_mode(j)!='required':return {'status':'not_checked','scope':'technical_only'}
    d,utterances,mapped,contract_file=load_contracts(j)
    cp=j.get('checkpoints',{}).get('images',{})
    entries=cp.get('scenes',[])
    if cp.get('visual_qa_status')!='pass' or len(entries)!=len(utterances):raise PermanentError('Visual quality: reviewed images checkpoint required')
    for i,(u,entry) in enumerate(zip(utterances,entries)):
        c=mapped[u['scene_id']];compiled=compile_prompt(u['visual_prompt'],d['project'],c)
        workflow=workflow_factory(compiled,i)
        key=conditioning_key(compiled['positive'],compiled['negative'],c,workflow)
        try:r=json.loads(Path(entry['review_path']).read_text(encoding='utf8'))
        except (OSError,ValueError,KeyError,TypeError) as e:raise PermanentError('Visual quality: review receipt missing/invalid') from e
        if entry.get('scene_id')!=u['scene_id'] or not receipt_passes(r,entry['path'],c,key):raise PermanentError('Visual quality: unreviewed/stale image, contract, workflow or reference')
    return {'status':'pass','scope':'artifact_bound_review','reviewer_accuracy_validated':False}
