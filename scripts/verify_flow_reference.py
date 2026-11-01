"""Download an existing Character and upload its ref; never generates a scene."""
import argparse,json,sqlite3,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from videostudio.providers import Pipeline
from videostudio.flow_reference_assets import ensure_portrait
from videostudio.comfy_references import upload_references


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--job',required=True);args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    with sqlite3.connect('file:'+str(root/'data/jobs.sqlite3')+'?mode=ro',uri=True) as db:
        row=db.execute('SELECT output FROM jobs WHERE id=?',(args.job,)).fetchone()
        if row is None:raise RuntimeError('Unknown job')
    manifest=json.loads((Path(row[0])/'flow-character-references.json').read_text(encoding='utf8'))
    reference=manifest['characters'][0]
    folder=root/'data/flow-reference-acceptance'/args.job;folder.mkdir(parents=True,exist_ok=True)
    pipeline=Pipeline.__new__(Pipeline);job={'id':args.job,'output':str(folder)}
    downloaded,assets=ensure_portrait(pipeline,job,reference,lambda:None)
    inputs,identity=upload_references('http://127.0.0.1:8188',args.job,[downloaded],folder/'prepared',lambda:None)
    report={'passed':True,'scope':'existing_flow_portrait_download_and_comfy_upload','character_name':reference['name'],'portrait_path':downloaded['portrait_path'],'comfy_inputs':inputs,'reference_identity':identity,'scene_generation_submitted':False}
    (folder/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8');print(json.dumps(report),flush=True)


if __name__=='__main__':main()
