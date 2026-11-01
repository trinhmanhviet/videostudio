import asyncio
import json
import os
import sys
import time
from pathlib import Path
import websockets

PORT_FILE = Path(os.environ["LOCALAPPDATA"]) / "Google" / "Chrome" / "User Data" / "DevToolsActivePort"

async def check():
    if not PORT_FILE.exists():
        print("NO_DEVTOOLS_PORT", flush=True)
        return
    lines = PORT_FILE.read_text().splitlines()
    port = lines[0].strip()
    path = lines[1].strip()
    ws_url = f"ws://127.0.0.1:{port}{path}"
    print(f"Connecting to ws://127.0.0.1:{port}...", flush=True)

    try:
        async with websockets.connect(ws_url, open_timeout=120) as ws:
            print("CDP_CONNECTED_OK", flush=True)
            await ws.send(json.dumps({"id": 1, "method": "Target.getTargets"}))
            res = json.loads(await ws.recv())
            targets = res.get("result", {}).get("targetInfos", [])
            print(f"TARGET_COUNT: {len(targets)}", flush=True)
            for t in targets:
                url = t.get("url", "")
                ttype = t.get("type", "")
                tid = t.get("targetId", "")
                print(f"T: {ttype} | {url[:60]} | {tid}", flush=True)
            return True
    except Exception as e:
        print(f"ERR: {type(e).__name__}: {e}", flush=True)
        return False

if __name__ == "__main__":
    asyncio.run(check())
