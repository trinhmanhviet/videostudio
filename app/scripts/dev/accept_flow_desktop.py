"""Real desktop HTTP acceptance: Chrome verifies, Python sends generation."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import urllib.parse
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from FlowAPI.client import FlowRequestClient, FlowRequestFailure
from FlowAPI.desktop import DesktopFlowClient
from FlowAPI.protocol import FlowRPCError
from accept_flow_request import PORTRAIT, WITH_REFERENCE, WITHOUT_REFERENCE, download_result


def save(path, state):
    temporary = path.with_suffix('.json.part')
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf8')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    parser.add_argument('--stage', required=True, choices=('project','character','portrait','with-reference','without-reference'))
    parser.add_argument('--client-id', help='Paired extension client in the same Chrome profile as cookie.txt')
    parser.add_argument('--server', default='http://localhost:8878')
    parser.add_argument('--attempt', type=int, default=1)
    options = parser.parse_args()
    if options.attempt < 1:
        raise ValueError('attempt must be positive')
    run = str(uuid.UUID(options.run))
    folder = ROOT.parent/'data'/'test-tmp/flow-desktop-acceptance'/run
    folder.mkdir(parents=True, exist_ok=True)
    path = folder/'run.json'
    state = json.loads(path.read_text(encoding='utf8')) if path.exists() else {
        'run_id':run,'transport':'desktop_httpx','project_name':'VS Desktop HTTP Test '+datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
        'results':{},'receipts':{},'downloads':{}}
    stage = options.stage
    if stage == 'project':
        operation, arguments = 'create_project', {'name':state['project_name']}
    elif stage == 'character':
        operation, arguments = 'create_character', {'project_id':state['results']['project']['project_id'],'name':'Minh_Desktop'}
    else:
        operation = 'generate_image'
        arguments = {'project_id':state['results']['project']['project_id'], 'references':[]}
        if stage == 'without-reference':
            arguments['prompt'] = WITHOUT_REFERENCE
        elif stage == 'portrait':
            arguments.update(prompt=PORTRAIT, target_character_id=state['results']['character']['character_id'])
        else:
            if not state['results'].get('portrait',{}).get('images'):
                raise ValueError('Reference test requires a real desktop-generated Character portrait')
            arguments.update(prompt=WITH_REFERENCE, references=[{'character_id':state['results']['character']['character_id'],'name':'Minh_Desktop'}])
        if not options.client_id:
            raise ValueError('Choose --client-id for the matching Chrome profile before generation')
    label = 'desktop:'+stage + (f':attempt:{options.attempt}' if options.attempt > 1 else '')
    request_id = str(uuid.uuid5(uuid.UUID(run), label))
    old = state['receipts'].get(stage)
    if old and old['id'] != request_id:
        if old.get('state') not in ('failed','blocked'):
            raise ValueError('Cannot replace a completed or unresolved request')
        state.setdefault('receipt_history',{}).setdefault(stage,[]).append(old)
    state['receipts'][stage] = {'id':request_id,'state':'prepared'}
    save(path,state)
    ua = None
    capture = ROOT.parent/'data'/'flow-api'/'network.har'
    if capture.exists():
        for entry in json.loads(capture.read_text(encoding='utf-8-sig'))['log']['entries']:
            if urllib.parse.urlsplit(entry['request']['url']).hostname == 'flow.google.com':
                ua = next((h['value'] for h in entry['request'].get('headers',[]) if h['name'].lower() == 'user-agent'),None)
                if ua:break
    client = DesktopFlowClient(ROOT.parent/'data'/'flow-api'/'cookie.txt',user_agent=ua)
    helper = FlowRequestClient(options.server,options.client_id)

    def verification(context):
        try:
            value = helper.acquire_verification(context)
        except FlowRequestFailure as error:
            code = (error.receipt.get('result') or {}).get('code','verification_unavailable')
            raise FlowRPCError('desktop_verification_failed','Chưa nhận được xác minh từ Chrome: '+code+'; generation chưa gửi') from None
        client.http.headers['User-Agent'] = value['user_agent']
        return value['token']

    try:
        result = client.submit(operation,arguments,request_id,verification_provider=verification if operation == 'generate_image' else None)
        state['results'][stage] = result
        state['receipts'][stage]['state'] = 'completed'
        save(path,state)
        if operation == 'generate_image' and stage not in state.setdefault('downloads',{}):
            state['downloads'][stage] = download_result(folder,stage,result)
            save(path,state)
        print(json.dumps({'transport':'desktop_httpx','stage':stage,'state':'completed','request_id':request_id,
                          'project_id':state['results']['project']['project_id'],'download':state.get('downloads',{}).get(stage)},ensure_ascii=True))
    except FlowRPCError as error:
        state['receipts'][stage].update(state='uncertain' if error.uncertain else 'failed',code=error.code,message=str(error))
        save(path,state)
        print(json.dumps({'transport':'desktop_httpx','stage':stage,'state':state['receipts'][stage]['state'],'code':error.code,'message':str(error)},ensure_ascii=True))
        raise SystemExit(1)
    finally:
        client.close()


if __name__ == '__main__':
    main()
