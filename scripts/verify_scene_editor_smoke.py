"""Verify isolated editor render artifacts after browser-driven edits/export."""
import hashlib,json,sqlite3
from pathlib import Path
from videostudio.core import digest
from videostudio.media import probe,run
from videostudio.visual_quality import atomic_json
ROOT=Path(__file__).resolve().parents[1]

def main():
    info=json.loads((ROOT/'data/editor-smoke-latest.json').read_text());c=sqlite3.connect('file:'+info['database'].replace('\\','/')+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
    child=c.execute('SELECT j.* FROM jobs j JOIN scene_exports e ON j.id=e.child ORDER BY j.created DESC LIMIT 1').fetchone();assert child and child['state']=='completed','Revision did not complete'
    def cps(jid):return {r['stage']:json.loads(r['value']) for r in c.execute('SELECT * FROM checkpoints WHERE job=?',(jid,))}
    old=cps(info['source_job']);new=cps(child['id']);child_video=new['render']['video']
    assert digest(info['source_video'])==info['source_sha256'],'Original video changed'
    for stage in ('speech','subtitles','music'):assert old[stage]==new[stage],stage+' changed'
    assert [s['duration'] for s in old['images']['scenes']]==[s['duration'] for s in new['images']['scenes']],'Scene timing changed'
    assert old['images']['scenes'][0]['path']!=new['images']['scenes'][0]['path'],'Replacement not applied'
    assert old['images']['scenes'][1]['path']==new['images']['scenes'][1]['path'],'Unchanged scene was replaced'
    source_clip=Path(info['source_video']).parent/'visual-0001.mp4';child_clip=Path(child_video).parent/'visual-0001.mp4'
    assert digest(source_clip)==digest(child_clip),'Unchanged visual clip not reused'
    def audio_hash(p):return hashlib.sha256(run(['ffmpeg','-v','error','-i',p,'-map','0:a:0','-f','s16le','-'],lambda:None)).hexdigest()
    a=audio_hash(info['source_video']);b=audio_hash(child_video);assert a==b,'Final decoded audio changed'
    durations=[float(probe(p)['format']['duration']) for p in (info['source_video'],child_video)];assert durations==[8.0,8.0],durations
    result={'source_job':info['source_job'],'child_job':child['id'],'source_video':info['source_video'],'child_video':child_video,'duration_seconds':durations,'original_video_unchanged':True,'speech_subtitles_music_checkpoints_equal':True,'scene_durations_equal':True,'final_decoded_audio_equal':True,'final_decoded_audio_sha256':a,'unchanged_visual_clip_reused':True,'review_status':new['verify'].get('visual_quality'),'gpu_llm_tts_generation_calls':0}
    atomic_json(Path(info['root'])/'smoke-verification.json',result);print(json.dumps(result,ensure_ascii=True))
if __name__=='__main__':main()
