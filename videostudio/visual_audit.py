"""Offline visual audit inventory. Does NOT call a model, generate or approve images.
python -m videostudio.visual_audit --job-dir ... --out ... [--labels ...]
"""
import argparse,json
from pathlib import Path
from .core import digest
from .visual_quality import atomic_json,bind_scene_ids,text_hash

def audit_existing(job_dir,output,labels=None):
    source=Path(job_dir).resolve();out=Path(output).resolve()
    if out==source or source in out.parents:raise ValueError('Audit output must be outside source job; original media are immutable')
    for name in ('audit.json','contracts-draft.json'):
        if (out/name).exists():raise ValueError('Existing audit output; choose a new output directory')
    path=source/'final-script.json'
    script=json.loads(path.read_text(encoding='utf8'))
    originals=bind_scene_ids(script['scenes'])
    label_doc=json.loads(Path(labels).read_text(encoding='utf8')) if labels else {'cases':[]}
    linked={}
    for case in label_doc.get('cases',[]):
        file=Path(case['image_path'])
        if not file.is_file() or digest(file)!=case['image_sha256']:raise ValueError('Regression label image is missing or changed')
        index=case.get('source_scene_index')
        if type(index) is int:linked.setdefault(index,[]).append({'case_id':case['case_id'],'label':case['expected'],'observations':case['observations'],'label_scope':case['label_scope'],'reviewed_image_path':str(file),'reviewed_image_sha256':case['image_sha256']})
    rows=[];draft=[]
    for index,scene in enumerate(originals):
        image=source/f'images-{index:04}.png'
        rows.append({'scene_id':scene['scene_id'],'index':index,'narration':scene['narration'],'visual_prompt':scene['visual_prompt'],'image_path':str(image),'image_sha256':digest(image) if image.is_file() else None,'visual_qa_status':'not_checked','reported_cases':linked.get(index,[])})
        draft.append({'scene_id':scene['scene_id'],'narration_sha256':text_hash(scene['narration']),'intent':None,'context':{},'must_show':[],'avoid':[],'references':[],'separate_subjects':False})
    job_id=None
    if (source/'brief.json').is_file():job_id=json.loads((source/'brief.json').read_text(encoding='utf8')).get('job_id')
    report={'schema_version':1,'job_dir':str(source),'final_script_sha256':digest(path),'reviewer_transport':'not_configured','visual_qa_status':'not_checked','scenes':rows,'limits':['This is an inventory, not automatic visual inspection.','Reported labels bind the exact reviewed screenshot/image, NOT unreviewed source pixels.','Draft contracts deliberately need human/verified planner completion before required mode can run.','Labels are narrow observations, not historical certification.']}
    atomic_json(out/'audit.json',report)
    atomic_json(out/'contracts-draft.json',{'schema_version':1,'job_id':job_id,'project':{'schema_version':1,'style':'','identities':[]},'scenes':draft})
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--job-dir',required=True);p.add_argument('--out',required=True);p.add_argument('--labels');a=p.parse_args()
    r=audit_existing(a.job_dir,a.out,a.labels)
    print(json.dumps({'output':str(Path(a.out).resolve()),'scene_count':len(r['scenes']),'status':r['visual_qa_status'],'reviewer_transport':r['reviewer_transport'],'gpu_submissions':0,'source_files_modified':False},ensure_ascii=False))
if __name__=='__main__':main()
