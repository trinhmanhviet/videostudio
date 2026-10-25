"""Isolated short render/UI fixture using existing assets; no LLM/TTS/GPU calls.
Run from repo: python -m scripts.scene_editor_smoke [--serve] [--port 8881]
"""
import argparse,json,os,shutil,uuid
from pathlib import Path
from videostudio.core import Store,STAGES,digest
from videostudio.media import asset,run,probe
from videostudio.captions import write_captions
from videostudio.scene_editor import SceneEditor
from videostudio.providers import Pipeline
from videostudio.visual_quality import atomic_json
ROOT=Path(__file__).resolve().parents[1]
ARMOR=Path(r'E:\Videos\1-000-nam-tien-hoa-cua-ao-giap-chau-au-cuoc-chay-dua-giua-th-20261025-032619')

class FixturePipeline(Pipeline):
    def __init__(self,store):self.store=store;self.ffmpeg='ffmpeg';self.ffprobe='ffprobe';self.scene_editor=SceneEditor(store)
    def preflight(self,scope=None):return {'ready':True,'checks':[{'name':'isolated_editor_fixture','ok':True,'detail':'No model generation permitted'}]}
    def handlers(self):return {'render':self.render,'verify':self.verify}

def build():
    root=ROOT/'data'/'editor-smoke'/uuid.uuid4().hex;root.mkdir(parents=True)
    store=Store(root/'jobs.sqlite3',root/'outputs');pipeline=FixturePipeline(store)
    request={'idea':'EDITOR SMOKE - isolated 8 second fixture','voice_id':'Thiện Minh','duration_seconds':8,'project':'EDITOR SMOKE (isolated)','quality_mode':'quick'}
    j,_=store.create(request,'source');out=Path(j['output']);origin=json.loads((ARMOR/'narration-attempt-03/script.json').read_text(encoding='utf8'));utterances=[];images=[];audio_assets=[];image_assets=[];cursor=0
    for i in range(2):
        wav=out/f'speech-{i:04}.wav';shutil.copy2(ARMOR/'narration-attempt-03'/wav.name,wav)
        duration=float(probe(wav)['format']['duration']);im=out/f'images-{i:04}.png';shutil.copy2(ARMOR/im.name,im)
        utterances.append({**origin['scenes'][i],'path':str(wav),'start':cursor,'end':cursor+duration,'duration':duration});cursor+=duration
        images.append({'path':str(im),'duration':duration});audio_assets.append(asset(wav));image_assets.append(asset(im))
    listing=out/'speech-concat.txt';listing.write_text('\n'.join("file '"+Path(u['path']).as_posix()+"'" for u in utterances),encoding='utf8')
    speech=out/'speech.wav';run(['ffmpeg','-v','error','-y','-f','concat','-safe','0','-i',listing,'-c:a','pcm_s16le',speech],lambda:None)
    images[-1]['duration']+=8-cursor
    caption=write_captions(utterances,out/'subtitles.srt');sub=Path(caption['ass_path'])
    music=out/'music.mp3';shutil.copy2(ARMOR/'music.mp3',music)
    cps={'plan':{'assets':[]},'research':{'sources':[],'assets':[]},'script':{'scenes':origin['scenes'][:2],'assets':[]},'speech':{'path':str(speech),'duration_seconds':cursor,'utterances':utterances,'assets':audio_assets+[asset(speech)]},'images':{'scenes':images,'assets':image_assets},'subtitles':{'path':str(sub),'srt_path':str(out/'subtitles.srt'),'assets':[asset(sub),asset(out/'subtitles.srt')]},'music':{'path':str(music),'assets':[asset(music)]}}
    j['checkpoints']=cps;cps['render']=pipeline.render(j,lambda:None);cps['verify']=pipeline.verify(j,lambda:None)
    with store.db() as c:
        for stage,cp in cps.items():c.execute('INSERT INTO checkpoints VALUES(?,?,?)',(j['id'],stage,json.dumps(cp,ensure_ascii=False)));atomic_json(out/(stage+'.json'),cp)
        c.execute("UPDATE jobs SET state='completed',stage='verify' WHERE id=?",(j['id'],))
    info={'root':str(root),'database':str(store.path),'source_job':j['id'],'source_video':str(out/'video.mp4'),'source_sha256':digest(out/'video.mp4'),'source_speech_sha256':digest(speech),'source_subtitles_sha256':digest(sub),'duration':8,'gpu_calls':0}
    atomic_json(root/'smoke-info.json',info);atomic_json(ROOT/'data'/'editor-smoke-latest.json',info)
    print(json.dumps(info),flush=True)
    return store,pipeline,info

def main():
    p=argparse.ArgumentParser();p.add_argument('--serve',action='store_true');p.add_argument('--reuse',action='store_true');p.add_argument('--port',type=int,default=8881);a=p.parse_args()
    if a.reuse:
        info=json.loads((ROOT/'data/editor-smoke-latest.json').read_text());store=Store(info['database'],Path(info['root'])/'outputs');pipeline=FixturePipeline(store)
    else:store,pipeline,info=build()
    if a.serve:
        import uvicorn
        from videostudio.api import create_app
        uvicorn.run(create_app(store,pipeline,True),host='127.0.0.1',port=a.port,log_level='warning')
if __name__=='__main__':main()
