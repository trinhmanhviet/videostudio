import math,shutil,struct,tempfile,unittest,wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from videostudio.providers import Pipeline

class Worker:
    batch_size=4
    calls=[]
    sizes=[]
    def __init__(self,*args):self.sizes.append(args[4] if len(args)>4 else None)
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def write_line(self,*args):raise AssertionError('expected batched generation')
    def write_lines(self,texts,outputs,on_complete):
        self.calls.append(list(texts))
        for index,path in enumerate(outputs):
            with wave.open(str(path),'wb') as output:
                output.setparams((1,2,48000,0,'NONE','not compressed'))
                output.writeframes(b''.join(struct.pack('<h',int(3000*math.sin(2*math.pi*440*i/48000))) for i in range(24000)))
            on_complete(index)

@unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
class SpeechPipelineBatchTests(unittest.TestCase):
    def test_batch_keeps_utterance_boundaries_and_retry_generates_only_missing_line(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);Worker.calls=[];Worker.sizes=[]
            voices=SimpleNamespace(root=root,selected=lambda _:dict(id='voice',kind='preset'))
            pipeline=Pipeline(voices)
            job={'id':'job','output':str(root),'request':{'voice_id':'voice','speech_batch_size':33},'checkpoints':{'script':{'scenes':[
                {'scene_id':'s1','narration_lines':['Câu thứ nhất.','Câu thứ hai.']},
                {'scene_id':'s2','narration':'Câu thứ ba.'}]}}}
            with patch('videostudio.providers.SpeechJob',Worker):
                first=pipeline._speech_attempt(job,lambda:None,root)
                self.assertEqual(Worker.sizes,[33])
                self.assertEqual(Worker.calls,[['Câu thứ nhất.','Câu thứ hai.','Câu thứ ba.']])
                self.assertEqual([u['narration'] for u in first['utterances']],Worker.calls[0])
                self.assertEqual([u['scene_id'] for u in first['utterances']],['s1','s1','s2'])
                self.assertEqual([u['start'] for u in first['utterances']],[0,.5,1.])
                original=(root/'speech-0000.wav').read_bytes()
                (root/'speech-0001.wav').unlink()
                job['request']['speech_batch_size']=512
                second=pipeline._speech_attempt(job,lambda:None,root)
                self.assertEqual(Worker.calls[-1],['Câu thứ hai.'])
                self.assertEqual(Worker.sizes,[33,512])
                self.assertEqual((root/'speech-0000.wav').read_bytes(),original)
                self.assertEqual(len(second['utterances']),3)
