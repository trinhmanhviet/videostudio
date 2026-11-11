import unittest
from pathlib import Path
from videostudio.scene_editor import SceneEditor


class EditorGroupIdentityTests(unittest.TestCase):
    def job(self):
        return {'checkpoints':{
            'speech':{'utterances':[
                {'scene_id':'scene-a','scene_index':0,'narration':'Same words','start':0,'end':2},
                {'scene_id':'scene-a','scene_index':0,'narration':'Second sentence','start':2,'end':4},
                {'scene_id':'scene-b','scene_index':1,'narration':'Same words','start':4,'end':6}]},
            'images':{'scenes':[{'path':'a.png','duration':4},{'path':'b.png','duration':2}],
                      'assets':[{'path':str(Path(p).resolve()),'sha256':'hash'} for p in ('a.png','b.png')]}}}

    def test_shared_id_within_scene_is_grouped_before_identity_validation(self):
        editor=SceneEditor.__new__(SceneEditor)
        rows,_=editor._layout(self.job())
        self.assertEqual([r['scene_id'] for r in rows],['scene-a','scene-b'])
        self.assertEqual(rows[0]['narration'],'Same words Second sentence')
        self.assertEqual((rows[0]['start'],rows[0]['end']),(0,4))

    def test_legacy_utterances_without_ids_are_still_supported(self):
        job=self.job()
        for u in job['checkpoints']['speech']['utterances']:u.pop('scene_id')
        rows,_=SceneEditor.__new__(SceneEditor)._layout(job)
        self.assertEqual(len({r['scene_id'] for r in rows}),2)

    def test_same_id_on_distinct_scenes_is_still_rejected(self):
        job=self.job();job['checkpoints']['speech']['utterances'][2]['scene_id']='scene-a'
        with self.assertRaises(ValueError):SceneEditor.__new__(SceneEditor)._layout(job)
