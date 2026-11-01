import asyncio
import json
import os
from pathlib import Path
import websockets

async def check():
    port_file = Path(os.environ["LOCALAPPDATA"]) / "Google" / "Chrome" / "User Data" / "DevToolsActivePort"
    lines = port_file.read_text().splitlines()
    port = lines[0].strip()
    path = lines[1].strip()
    ws_url = f"ws://127.0.0.1:{port}{path}"
    print(f"Connecting to: {ws_url}", flush=True)

    try:
        async with websockets.connect(ws_url, open_timeout=10) as ws:
            print("Connected!", flush=True)
            await ws.send(json.dumps({"id": 1, "method": "Target.getTargets"}))
            res = await ws.recv()
            data = json.loads(res)
            targets = data.get("result", {}).get("targetInfos", [])
            print(f"SUCCESS! Total targets: {len(targets)}", flush=True)
            for t in targets:
                if t.get("type") == "page":
                    print(f"  - [{t.get('type')}] {t.get('title')} ({t.get('url')})", flush=True)
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}", flush=True)

if __name__ == "__main__":
    asyncio.run(check())
