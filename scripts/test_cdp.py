import asyncio
import json
import os
from pathlib import Path
import websockets

async def check_cdp():
    port_file = Path(os.environ["LOCALAPPDATA"]) / "Google" / "Chrome" / "User Data" / "DevToolsActivePort"
    if not port_file.exists():
        print("DevToolsActivePort not found")
        return False
    lines = port_file.read_text().splitlines()
    port = lines[0].strip()
    path = lines[1].strip()
    ws_url = f"ws://127.0.0.1:{port}{path}"
    print(f"Connecting to {ws_url}...")
    try:
        async with websockets.connect(ws_url, open_timeout=60) as ws:
            await ws.send(json.dumps({"id": 1, "method": "Target.getTargets"}))
            msg = await ws.recv()
            data = json.loads(msg)
            targets = data.get("result", {}).get("targetInfos", [])
            print(f"SUCCESS! Connected to Chrome CDP. Total targets: {len(targets)}")
            for t in targets:
                if t.get("type") == "page":
                    print(f"  - [{t.get('type')}] {t.get('title')}: {t.get('url')}")
            return True
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Failed to connect: {repr(e)}")
        return False

if __name__ == "__main__":
    asyncio.run(check_cdp())
