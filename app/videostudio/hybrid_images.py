"""Progress-preserving Flow -> two Comfy batches -> single Flow probe routing."""
from .paths import DATA_ROOT
import json
from pathlib import Path
from PIL import Image
from .core import digest,PermanentError
from .media import asset
from .cdp_flow import normalize_flow_prompt


def comfy_scene(pipeline,job,task,references,check):
    from .providers import image_graph,image_seed,SCENE_SIZE,scene_image_prompt
    from .flow_reference_assets import ensure_portrait
    from .comfy_references import upload_references,reference_graph
    selected=[];assets=[]
    for mention in task.get('character_mentions',[]):
        found=next((r for r in references.values() if r['name']==mention['name'] and r['character_id']==mention['character_id']),None)
        if not found:raise PermanentError('Comfy fallback lacks the exact native reference: '+mention['name'])
        found,files=ensure_portrait(pipeline,job,found,check);selected.append(found);assets.extend(files)
    names=[];identities=[]
    if selected:names,identities=upload_references(pipeline.comfy,job['id'],selected,Path(job['output'])/'comfy-references',check,canvas=SCENE_SIZE)
    prompt=normalize_flow_prompt(scene_image_prompt(task['original_prompt'],wide=True),task.get('character_mentions'))
    if selected:prompt='Use the supplied images only for identity, not their background or layout. '+ ' '.join(f'Reference image {i+1}: {r["name"]}.' for i,r in enumerate(selected))+' Render one full-frame scene, not a collage. '+prompt
    kind=f'images-hybrid-{task["ordinal"]:04}';prefix='videostudio/'+job['id']+'-'+kind
    seed=image_seed(job,task['ordinal']);graph=reference_graph(prompt,seed,prefix,names,size=SCENE_SIZE) if names else image_graph(prompt,seed,prefix,size=SCENE_SIZE)  # stands in for a landscape Flow picture
    identity={'prompt':task['original_prompt'],'references':identities,'graph':graph}
    binding=Path(job['output'])/(kind+'.conditioning.json')
    if binding.is_file():
        if json.loads(binding.read_text(encoding='utf8'))!=identity:raise PermanentError('Comfy fallback conditioning changed; keeping old receipt')
    else:
        if task['output_path'].exists() or (Path(job['output'])/(kind+'-receipt.json')).exists():raise PermanentError('Comfy output lacks conditioning identity')
        binding.write_text(json.dumps(identity,ensure_ascii=False),encoding='utf8')
    result=pipeline.comfy_asset(job,kind,graph,task['output_path'],check)
    with Image.open(task['output_path']) as picture:picture.load();width,height=picture.size
    return {'task_id':task['task_id'],'request_id':result['prompt_id'],'width':width,'height':height,'provider':'comfy','hybrid_fallback':True,'reference_images':identities,'reference_assets':assets+[asset(binding)]}


def run(pipeline,job,tasks,batch_size,references,on_result,check,*,timeout=2400):
    from .providers import ROOT,UncertainDeliveryError
    path=Path(job['output'])/'image-routing.json'
    state=json.loads(path.read_text(encoding='utf8')) if path.is_file() else {'job_id':job['id'],'mode':'flow','remaining':0,'probe':False}
    if state.get('job_id')!=job['id']:raise PermanentError('Hybrid route belongs to another job')
    pending=list(tasks);results={}
    def save():
        temporary=path.with_suffix('.part.json');temporary.write_text(json.dumps(state),encoding='utf8');temporary.replace(path)
    while pending:
        check()
        if state['mode']=='comfy':
            task=pending[0];receipt_path=DATA_ROOT/'flow-images/tasks'/(task['task_id']+'.json')
            prior=json.loads(receipt_path.read_text(encoding='utf8')) if receipt_path.is_file() else None
            if prior and (prior.get('job_id')!=pipeline._active_flow_run(job) or prior.get('character_mentions',[])!=task.get('character_mentions',[])):raise UncertainDeliveryError('Flow fallback receipt identity differs')
            if prior and prior.get('blocked_confirmed') is not True:raise UncertainDeliveryError('Flow scene is not confirmed failed; reconcile before switching providers')
            if getattr(pipeline,'store',None):pipeline.store.log(job['id'],'images',f'Flow bị chặn; tạo cảnh {task["ordinal"]+1} bằng Comfy. Còn {state["remaining"]} ảnh trước khi thử lại Flow.')
            result=comfy_scene(pipeline,job,task,references,check);on_result(task,result)
            results[task['task_id']]=result;pending.pop(0);state['remaining']-=1
            if state['remaining']<=0:state.update(mode='flow',probe=True)
            save();continue
        size=1 if state.get('probe') else batch_size
        cohort=pipeline._flow_cohorts(pending,size)[0]
        submitted=[{**task,'reopen_project':True} for task in cohort] if state.get('probe') else cohort
        returned=pipeline._browser_scene_images_batch(job,submitted,check,timeout=timeout)
        if set(returned)!={task['task_id'] for task in cohort}:raise UncertainDeliveryError('Hybrid Flow result set differs')
        blocked=[]
        for task in cohort:
            result=returned[task['task_id']]
            if result.get('status')=='blocked' and result.get('blocked_confirmed') is True:blocked.append(task)
            else:
                on_result(task,result);results[task['task_id']]=result;pending.remove(task)
        if blocked:state.update(mode='comfy',remaining=2*batch_size,probe=False)
        else:state['probe']=False
        save()
    return results
