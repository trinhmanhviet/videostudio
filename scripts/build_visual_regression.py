"""Record agent-inspected images as regression labels; NEVER modify source job."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
JOB=Path(r'E:\Videos\1-000-nam-tien-hoa-cua-ao-giap-chau-au-cuoc-chay-dua-giua-th-20261025-032619')
MEDIA=Path(r'C:\Users\leath\aicoworker\openclaw\media\outbound')
def main():
    script=json.loads((JOB/'final-script.json').read_text(encoding='utf8'))
    specs=[
        (174,'18016af8-339d-4ef1-811f-c36d6d02da70.png','reconstruction','fail',['Disposable blue masks and clear plastic shields replace historical armor components.']),
        (182,'32874c01-e74a-4c66-9d2c-27a557a18022.png','comparison','fail',['Ancient-style helmet and metal shoulders fused to one modern nylon tactical vest. Comparison objects are not separated.']),
        (184,'3855b436-469d-4206-a354-5ae9bc963047.png','comparison','fail',['Split layout exists, but historical figure is not identified as European equipment; bottom helmet mixes metal armor with transparent modern visor.']),
        (156,'f86ae0f3-46dc-46ad-81b5-3cb364ae145c.png','reconstruction','fail',['Modern hook-and-loop-like woven straps and contemporary workshop equipment; medieval material constraints absent.']),
        (138,'6a743afd-f224-46dd-85cb-2851752b4116.png','reconstruction','fail',['Futuristic hybrid armor and gun-like object held near head, inconsistent with requested unarmed arm/torso movement.']),
    ]
    cases=[]
    for index,file,intent,verdict,defects in specs:
        path=MEDIA/file; scene=script['scenes'][index]
        cases.append({'case_id':f'armor-{index:04}', 'source_scene_index':index,'intent':intent,'image_path':str(path),'image_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'narration':scene['narration'],'original_prompt':scene['visual_prompt'],'expected':verdict,'observations':defects,'label_origin':'agent native pixel inspection + user defect reports','label_scope':'visible defects, not comprehensive historical authentication'})
    end=JOB/'images-0195.png'
    cases.append({'case_id':'forge-ending-control','source_scene_index':195,'intent':'reconstruction','image_path':str(end),'image_sha256':hashlib.sha256(end.read_bytes()).hexdigest(),'narration':script['scenes'][195]['narration'],'original_prompt':script['scenes'][195]['visual_prompt'],'expected':'pass','observations':['Visible anvil and resting wood-handled hammer match ending. No obvious tactical/PPE hybrid.'],'label_origin':'agent native pixel inspection','label_scope':'object/action control only; precise era and metallurgy not certified'})
    # Same pixels, different explicit task: modern objects are NOT globally forbidden.
    modern=dict(cases[0]);modern.update(case_id='modern-ppe-control',source_scene_index=None,intent='contemporary',narration='Display modern safety masks and face shields in a prop workshop.',original_prompt='Two modern PPE masks and clear face shields on stands in a workshop.',expected='pass',observations=['Disposable masks and face shields are the explicitly requested objects.'],label_scope='subject match under alternate modern intent only; not acceptance of original historical scene')
    cases.append(modern)
    out=ROOT/'tests/fixtures/visual-regression.json';out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps({'schema_version':1,'source_job':str(JOB),'limitations':['Control labels are narrow visual checks, not historical certification.','No autonomous VLM transport evaluated; these labels are not predictions.','Existing images are referenced by hash, not edited or regenerated.'],'cases':cases},ensure_ascii=False,indent=2),encoding='utf8')
    print(out, len(cases),'cases; no source files modified')
if __name__=='__main__':main()
