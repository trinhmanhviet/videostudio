"""Old multipart receipts are imported by the one current writer."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from videostudio.core import digest, PermanentError
from videostudio import meme_animation
from videostudio.meme_migration import legacy_prefix
from videostudio.meme_animation_script import AnimationCatalog

ROOT = Path(__file__).resolve().parents[1]


class SavedPartTests(unittest.TestCase):
    def save(self,path,value):
        path.write_text(json.dumps(value),encoding='utf8')
        path.with_suffix('.receipt.json').write_text(json.dumps({'sha256':digest(path),'identity':'original'}),encoding='utf8')

    def test_saved_prefix_is_passed_to_current_writer_with_original_text(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            data = json.loads((ROOT/'tests/fixtures/meme-animation-script.json').read_text(encoding='utf8'))
            request={'idea':'Saved story','voice_id':'test','duration_seconds':420,'workflow_mode':'meme','meme_engine':'hyperframes'}
            job={'output':folder,'request':request,'checkpoints':{}}
            parts=Path(folder)/'animation-parts';parts.mkdir()
            outline={k:v for k,v in data.items() if k!='beats'}
            outline['parts']=[{'summary':'Already narrated.','ending':'Continue.'},{'summary':'Finish story.','ending':'Original ending.'}]
            self.save(parts/'outline.json',outline)
            self.save(parts/'part-01.json',{'part':1,'beats':data['beats']})
            before={p.name:p.read_bytes() for p in parts.iterdir()}
            with patch('videostudio.comedy_story.write_story',return_value={'ok':True}) as writer:
                self.assertEqual(meme_animation.script(SimpleNamespace(),job,lambda:None),{'ok':True})
            prefix=writer.call_args.kwargs['legacy_prefix']
            self.assertEqual([b['text'] for b in prefix['parts'][0]['beats']],[b['text'] for b in data['beats']])
            self.assertEqual(prefix['total_parts'],2)
            self.assertEqual(before,{p.name:p.read_bytes() for p in parts.iterdir()})
            # An interruption after receiving valid JSON but before the final
            # receipt must not resend the same completed part to the model.
            raw_path=parts/'part-02-originalidentity-attempt-00.json'
            raw_path.write_text(json.dumps({'part':2,'beats':data['beats']}),encoding='utf8')
            recovered=legacy_prefix(job,AnimationCatalog())
            self.assertEqual(len(recovered['parts']),2)
            self.assertEqual(recovered['parts'][1]['beats'],prefix['parts'][0]['beats'])
            (parts/'part-01.json').write_text('{}',encoding='utf8')
            with self.assertRaisesRegex(PermanentError,'receipt'):
                legacy_prefix(job,AnimationCatalog())
