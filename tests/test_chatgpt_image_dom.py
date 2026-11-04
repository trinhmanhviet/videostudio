"""DOM regressions from the read-only 2026-11-04 ChatGPT probe."""
import json
import shutil
import subprocess
import unittest
from unittest.mock import patch
from videostudio.cdp_images import image_snapshot,match_image

# Small DOM contract fixture: includes the hidden print-label suffix observed
# in production. Run the actual generated expressions, not a rewritten parser.
DOM = r"""
const input=JSON.parse(process.argv[1]);
const marker='[VideoStudio image request '+ 'e'.repeat(64)+']';
const user={textContent:'Create image '+marker};
const heading={textContent:input.legacy?'You said:':'You said:You',parentElement:user,
  querySelector:()=>null,getAttribute:key=>key==='data-conversation-role'&&!input.legacy?'user':null};
const image={currentSrc:'blob:https://chatgpt.com/fixture',naturalWidth:941,naturalHeight:1672,complete:true};
const button={disabled:false,querySelector:()=>image,scrollIntoView(){},contains:()=>true,
  getBoundingClientRect:()=>({x:10,y:10,width:100,height:100})};
const turn={innerText:'Create image '+marker,getAttribute:()=>input.state||'complete',
 querySelector:selector=>selector.includes('data-conversation-role')&&!input.legacy?heading:
    selector.includes('data-message-author-role')||selector.includes('data-chatgpt-search-unit-key')?(!input.legacy&&!input.headingOnly?user:null):null,
 querySelectorAll:selector=>selector==='h4'?[heading]:selector.includes('generated-image-preview')?[image]:[]};
const other={...turn,innerText:marker,querySelector:()=>null,
 querySelectorAll:selector=>selector==='h4'?[{textContent:'ChatGPT said:ChatGPT',parentElement:{textContent:marker},querySelector:()=>null,getAttribute:()=> 'assistant'}]:selector.includes('generated-image-preview')?[image]:[]};
const document={querySelectorAll:selector=>selector==='[data-talvt-turn-state]'?(input.assistantOnly?[other]:input.duplicate?[turn,turn]:[turn]):[]};
const result=eval(input.expression);process.stdout.write(JSON.stringify(result));
"""

@unittest.skipUnless(shutil.which('node'),'Node required for DOM expression test')
class ImageDOMTests(unittest.TestCase):
    marker='[VideoStudio image request '+'e'*64+']'
    def snapshot(self,**options):
        with patch('videostudio.cdp_images.snapshot_expression',return_value='({mode:"chat",login:false,challenge:false})'):
            expression=image_snapshot(self.marker)
        result=subprocess.run(['node','-e',DOM,json.dumps(dict(expression=expression,**options))],capture_output=True,text=True,check=True)
        return json.loads(result.stdout)
    def test_semantic_user_block_correlates_despite_hidden_print_label(self):
        state=self.snapshot()
        self.assertIn(self.marker,state['image_turns'][0]['user'])
        self.assertEqual(match_image(state,self.marker)['width'],941)
    def test_role_heading_alone_also_handles_you_said_you(self):
        state=self.snapshot(headingOnly=True)
        self.assertIsNotNone(match_image(state,self.marker))
    def test_legacy_heading_remains_supported(self):
        self.assertIsNotNone(match_image(self.snapshot(legacy=True),self.marker))
    def test_assistant_echo_of_marker_is_not_a_user_receipt(self):
        self.assertIsNone(match_image(self.snapshot(assistantOnly=True),self.marker))
    def test_streaming_and_ambiguous_turns_still_reject(self):
        self.assertIsNone(match_image(self.snapshot(state='streaming'),self.marker))
        with self.assertRaises(ValueError):match_image(self.snapshot(duplicate=True),self.marker)
