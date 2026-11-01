import asyncio
import json
import os
from pathlib import Path
import websockets

PORT_FILE = Path(os.environ["LOCALAPPDATA"]) / "Google" / "Chrome" / "User Data" / "DevToolsActivePort"

async def test_session():
    lines = PORT_FILE.read_text().splitlines()
    port = lines[0].strip()
    path = lines[1].strip()
    browser_ws = f"ws://127.0.0.1:{port}{path}"

    async with websockets.connect(browser_ws, open_timeout=5) as ws:
        print("Connected to Browser WS!", flush=True)

        # 1. Get targets
        await ws.send(json.dumps({"id": 1, "method": "Target.getTargets"}))
        res = json.loads(await ws.recv())
        targets = res.get("result", {}).get("targetInfos", [])
        chatgpt = next((t for t in targets if "chatgpt.com" in t.get("url", "")), None)
        target_id = chatgpt["targetId"]
        print(f"Target: {target_id} ({chatgpt['url']})", flush=True)

        # 2. Attach to target
        await ws.send(json.dumps({
            "id": 2,
            "method": "Target.attachToTarget",
            "params": {"targetId": target_id, "flatten": True}
        }))
        attach_res = json.loads(await ws.recv())
        session_id = attach_res.get("result", {}).get("sessionId")
        print(f"Attached! SessionId: {session_id}", flush=True)

        # 3. Evaluate JavaScript in page session
        await ws.send(json.dumps({
            "id": 3,
            "sessionId": session_id,
            "method": "Runtime.evaluate",
            "params": {"expression": "document.title", "returnByValue": True}
        }))
        eval_res = json.loads(await ws.recv())
        val = eval_res.get("result", {}).get("result", {}).get("value")
        print(f"Title from Page Session: {val}", flush=True)

if __name__ == "__main__":
    asyncio.run(test_session())
