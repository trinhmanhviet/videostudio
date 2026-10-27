"""One explicit, synthetic WebAuth text smoke. No VideoStudio job or browser restart."""
import json
import os
from pathlib import Path
from videostudio.webauth import MODEL, SMOKE_RESPONSE, request_json


def main():
    response = request_json('Return exactly one JSON object with these fields and no other fields: '
                            '{"connection_test":"videostudio-webauth","ok":true}', lambda: None)
    if response != SMOKE_RESPONSE:
        raise SystemExit('WebAuth returned a response, but not the exact expected smoke JSON. No acceptance receipt written.')
    receipt = Path(os.getenv('VS_WEBAUTH_SMOKE', str(Path(__file__).resolve().parents[1] / 'data' / 'webauth-smoke.json')))
    receipt.parent.mkdir(parents=True, exist_ok=True)
    temporary = receipt.with_name(receipt.name + '.part')
    temporary.write_text(json.dumps({'completed': True, 'model': MODEL, 'response': response}), encoding='utf-8')
    temporary.replace(receipt)
    print('WebAuth synthetic text smoke accepted.')


if __name__ == '__main__':
    main()
