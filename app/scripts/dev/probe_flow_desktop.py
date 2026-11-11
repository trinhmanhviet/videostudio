"""Read-only desktop authentication probe. Never creates media or exports cookies."""
import argparse
import json
from pathlib import Path
import sys
import urllib.parse
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from FlowAPI.desktop import DesktopFlowClient
from FlowAPI.protocol import FlowRPCError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cookies', default=str(ROOT.parent/'data'/'flow-api'/'cookie.txt'))
    parser.add_argument('--project-id')
    options = parser.parse_args()
    user_agent = None
    capture = ROOT.parent/'data'/'flow-api'/'network.har'
    if capture.exists():
        for entry in json.loads(capture.read_text(encoding='utf-8-sig'))['log']['entries']:
            if urllib.parse.urlsplit(entry['request']['url']).hostname != 'flow.google.com':
                continue
            user_agent = next((header['value'] for header in entry['request'].get('headers', []) if header['name'].lower() == 'user-agent'), None)
            if user_agent:
                break
    client = DesktopFlowClient(options.cookies, user_agent=user_agent)
    try:
        bootstrap = client.bootstrap()
        projects = client.submit('list_projects', {}, str(uuid.uuid4()))['projects']
        result = {**bootstrap, 'transport': 'desktop_httpx', 'project_count': len(projects)}
        if options.project_id:
            result['test_project_found'] = any(project['project_id'] == options.project_id for project in projects)
        print(json.dumps(result))
    except FlowRPCError as error:
        print(json.dumps({'ready': False, 'transport': 'desktop_httpx', 'code': error.code, 'message': str(error),
                          'cookie_presence': client.cookie_presence}, ensure_ascii=True))
        raise SystemExit(1)
    finally:
        client.close()


if __name__ == '__main__':
    main()
