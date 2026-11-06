import copy,json,unittest
from pathlib import Path
from videostudio.meme_animation_script import AnimationCatalog,validate

ROOT=Path(__file__).resolve().parents[1]

class ComedyVisualTests(unittest.TestCase):
 def test_actor_alias_in_reaction_is_compiled_to_native_who_without_changing_identity(self):
  raw=json.loads((ROOT/'tests/fixtures/meme-animation-script.json').read_text(encoding='utf8'))
  raw['beats'][0]['punch']={'actor':'ban','face':'soc'}
  result=validate(raw,AnimationCatalog(),{'voice_id':'test','duration_seconds':20})
  self.assertEqual(result['beats'][0]['punch'],{'who':'ban','face':'soc'})
  raw['beats'][0]['punch']['who']='toi'
  with self.assertRaises(ValueError):validate(raw,AnimationCatalog(),{'voice_id':'test','duration_seconds':20})
 def test_props_and_comic_pauses_survive_the_engine_contract(self):
  raw=json.loads((ROOT/'tests/fixtures/meme-animation-script.json').read_text(encoding='utf8'))
  raw['props']={'book':{'asset':None,'label':'Cuốn sách'}}
  raw['beats'][0].update(props={'book':{'placement':'held','owner':'toi'}},pause_before=.25,pause_after=.4,reaction_seconds=.7)
  result=validate(raw,AnimationCatalog(),{'voice_id':'test','duration_seconds':20})
  self.assertEqual(result['props']['book']['label'],'Cuốn sách')
  self.assertEqual(result['beats'][0]['props']['book']['owner'],'toi')
  self.assertEqual(result['beats'][0]['pause_before'],.25)
  raw['beats'][0]['pause_before']=float('nan')
  with self.assertRaises(ValueError):validate(raw,AnimationCatalog(),{'voice_id':'test','duration_seconds':20})

 def test_prop_layer_escapes_text_and_renders_held_table_hidden_states(self):
  from memestudio.engine.prop_layer import layer
  props={'book':{'asset':'book','label':'<script>book</script>'}}
  beat={'i':0,'start':.2,'end':2,'props':{'book':{'placement':'held','owner':'toi'}}}
  sc={'id':'block_0','start':0,'end':3,'x':{'toi':500},'beats':[beat]}
  library={'book':ROOT/'memestudio/assets/rig/parts/component_017.png'}
  html=layer(props,sc,library,lambda a,b:b,owner='toi')
  self.assertIn('&lt;script&gt;book&lt;/script&gt;',html);self.assertNotIn('<script>',html)
  self.assertIn('prop_book',html)
  self.assertNotIn('<span',html)
  self.assertEqual(layer(props,sc,{},lambda a,b:b,owner='toi'),'')
  beat['props']['book']['placement']='hidden'
  self.assertEqual(layer(props,sc,library,lambda a,b:b,owner='toi'),'')

 def test_table_props_remain_in_their_location_when_the_story_changes_rooms(self):
  from memestudio.engine.prop_layer import layer
  props={'sign':{'asset':'sign','label':'Bảng giá'}}
  beat={'i':0,'start':0,'end':1,'_prop_states':{'sign':{'placement':'table','owner':None,'_location':'office'}}}
  scene={'id':'s','location':'home','end':1,'x':{},'beats':[beat]}
  library={'sign':ROOT/'memestudio/assets/rig/parts/component_017.png'}
  self.assertEqual(layer(props,scene,library,lambda a,b:b),'')
  scene['location']='office';self.assertIn('prop_sign',layer(props,scene,library,lambda a,b:b))
