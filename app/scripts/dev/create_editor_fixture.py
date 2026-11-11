"""Build synthetic media ONLY under this checkout's data/editor-fixture directory."""
import json,math,random,struct,wave
from pathlib import Path
from PIL import Image,ImageDraw
from videostudio.core import Store
from videostudio.media import asset,render,verify
from videostudio.captions import write_captions

ROOT=Path(__file__).resolve().parents[2]
FIXTURE=ROOT.parent/'data'/'editor-fixture'

def create_fixture():
    FIXTURE.mkdir(parents=True,exist_ok=True)
    store=Store(FIXTURE/'jobs.sqlite3',FIXTURE/'outputs')
    saved=FIXTURE/'info.json'
    if saved.is_file():
        info=json.loads(saved.read_text(encoding='utf8'))
        try:
            job=store.get(info['job_id'])
            if job['state']=='completed' and Path(job['checkpoints']['render']['video']).is_file():return store,info
        except (KeyError,OSError):pass
    request={'idea':'Hành trình qua bầu trời đêm — dữ liệu thử tổng hợp','voice_id':'fixture','duration_seconds':8,'project':'Bàn dựng thử nghiệm','image_provider':'comfy','edit_preset':'science'}
    job,_=store.create(request,'editor-synthetic-source-v1');folder=Path(job['output']);images=[];image_assets=[]
    timings=[(0,2.5),(2.5,5),(5,8)]
    for index,(start,end) in enumerate(timings):
        image=Image.new('RGB',(768,1376));pixels=image.load();rng=random.Random(120+index)
        for y in range(1376):
            for x in range(768):
                light=math.exp(-((x-160-index*160)**2/140000+(y-600)**2/320000))
                pixels[x,y]=(int(9+light*(40+index*8)),int(14+light*(24+index*15)),int(28+light*(80-index*6)))
        draw=ImageDraw.Draw(image)
        for _ in range(350):
            x,y=rng.randrange(768),rng.randrange(1376);r=rng.choice([1,1,1,2]);color=rng.randrange(100,240);draw.ellipse((x-r,y-r,x+r,y+r),fill=(color,color,min(255,color+10)))
        draw.ellipse((70+index*150,430,390+index*100,750),fill=['#547786','#b79064','#7777a2'][index],outline='#c9d9dc',width=2)
        path=folder/f'image-{index:04}.png';image.save(path)
        images.append({'path':str(path),'duration':end-start,'scene_id':f'scene-{index:04}','image_provider':'upload'});image_assets.append(asset(path))
    lines=['Một khoảng trời mở ra trước mắt.','Những vì sao kể lại chuyện xa xưa.','Ánh sáng đã đi qua nhiều thế kỷ.','Mỗi dấu vết đều giữ một câu chuyện.','Ta nhìn lên và đặt thêm câu hỏi.','Hành trình khám phá vẫn tiếp diễn.']
    utterances=[];speech_assets=[];combined=[]
    for i,line in enumerate(lines):
        start=i*8/6;end=(i+1)*8/6;count=round((end-start)*16000)
        frames=b''.join(struct.pack('<h',int(1800*math.sin(2*math.pi*(180+i*28)*s/16000)*(0.65+0.35*math.sin(math.pi*s/count)))) for s in range(count))
        path=folder/f'speech-{i:04}.wav'
        with wave.open(str(path),'wb') as out:out.setparams((1,2,16000,0,'NONE','not compressed'));out.writeframes(frames)
        combined.append(frames);speech_assets.append(asset(path));utterances.append({'scene_id':f'scene-{min(2,int(start/2.5)):04}','scene_index':min(2,int(start/2.5)),'chapter_index':1 if start<5 else 2,'narration':line,'visual_prompt':'Synthetic night sky fixture','path':str(path),'start':start,'end':end,'duration':end-start})
    speech=folder/'speech.wav'
    with wave.open(str(speech),'wb') as out:out.setparams((1,2,16000,0,'NONE','not compressed'));out.writeframes(b''.join(combined))
    music=folder/'music.wav'
    with wave.open(str(music),'wb') as out:
        out.setparams((1,2,16000,0,'NONE','not compressed'));out.writeframes(b''.join(struct.pack('<h',int(500*math.sin(2*math.pi*110*s/16000)+250*math.sin(2*math.pi*165*s/16000))) for s in range(128000)))
    captions=write_captions(utterances,folder/'subtitles.srt')
    captions['srt_path']=str(folder/'subtitles.srt')
    scene_rows=[{'scene_id':f'scene-{i:04}','scene_index':i,'chapter_index':1 if i<2 else 2,'narration':' '.join(lines[i*2:i*2+2]),'visual_prompt':'Synthetic night sky fixture','start':start,'end':end,'duration':end-start} for i,(start,end) in enumerate(timings)]
    checkpoints={'plan':{'title':'Hành trình qua bầu trời đêm','music_prompt':'gentle ambient','assets':[]},'research':{'sources':[],'assets':[]},'script':{'title':'Hành trình qua bầu trời đêm','narration':' '.join(lines),'scenes':scene_rows,'chapters':[{'index':1,'title':'Ánh sáng xa xưa'},{'index':2,'title':'Tiếp tục khám phá'}],'assets':[]},'speech':{'path':str(speech),'duration_seconds':8,'scenes':scene_rows,'utterances':utterances,'assets':speech_assets+[asset(speech)]},'images':{'scenes':images,'image_provider':'comfy','assets':image_assets},'music':{'path':str(music),'duration_seconds':8,'assets':[asset(music)]},'subtitles':{'path':captions['ass_path'],'srt_path':captions['srt_path'],'assets':[asset(captions['ass_path']),asset(captions['srt_path'])]}}
    rendered=render(images,speech,music,captions['ass_path'],folder/'video.mp4',8,lambda:None)
    checkpoints.update(render=rendered,verify=verify(rendered['video'],8))
    with store.db() as connection:
        for stage,value in checkpoints.items():connection.execute('INSERT OR REPLACE INTO checkpoints VALUES(?,?,?)',(job['id'],stage,json.dumps(value,ensure_ascii=False)))
        connection.execute("UPDATE jobs SET state='completed',stage='verify' WHERE id=?",(job['id'],))
    info={'job_id':job['id'],'synthetic':True,'database':str(store.path),'output':str(folder)}
    saved.write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf8');return store,info

if __name__=='__main__':print(json.dumps(create_fixture()[1],ensure_ascii=False))
