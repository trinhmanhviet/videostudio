import unittest
from videostudio.providers import Pipeline

class CohortTests(unittest.TestCase):
    def test_ten_prompts_per_cohort_preserves_scene_order_and_small_tail(self):
        tasks=[{'ordinal':i,'prompt':f'scene {i}','character_mentions':[]} for i in range(23)]
        groups=Pipeline._flow_cohorts(tasks,10)
        self.assertEqual([len(g) for g in groups],[10,10,3])
        self.assertEqual([t['ordinal'] for g in groups for t in g],list(range(23)))
    def test_repeated_prompt_starts_next_cohort_instead_of_stopping_video(self):
        tasks=[{'ordinal':i,'prompt':prompt,'character_mentions':[]} for i,prompt in enumerate(['room','knife',' room ','person'])]
        groups=Pipeline._flow_cohorts(tasks,10)
        self.assertEqual([[t['ordinal'] for t in g] for g in groups],[[0,1],[2,3]])

if __name__=='__main__':unittest.main()
