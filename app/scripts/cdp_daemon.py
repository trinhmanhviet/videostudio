import asyncio
import json
import os
import sys
import time
from pathlib import Path
import websockets
from aiohttp import web

PORT_FILE = Path(os.environ["LOCALAPPDATA"]) / "Google" / "Chrome" / "User Data" / "DevToolsActivePort"

class ChromeCDPBridge:
    def __init__(self):
        self.ws = None
        self.chatgpt_tab_id = None
        self.lock = asyncio.Lock()

    async def ensure_connected(self):
        if self.ws is not None and not self.ws.closed:
            return True
        if not PORT_FILE.exists():
            print("DevToolsActivePort does not exist", flush=True)
            return False

        lines = PORT_FILE.read_text().splitlines()
        port = lines[0].strip()
        path = lines[1].strip()
        ws_url = f"ws://127.0.0.1:{port}{path}"
        print(f"Connecting to Chrome CDP: {ws_url}...", flush=True)

        try:
            self.ws = await websockets.connect(ws_url, open_timeout=30, ping_interval=20, ping_timeout=20)
            print("Successfully connected to Chrome CDP!", flush=True)

            # Discover ChatGPT tab
            await self.ws.send(json.dumps({"id": 1, "method": "Target.getTargets"}))
            res = json.loads(await self.ws.recv())
            targets = res.get("result", {}).get("targetInfos", [])
            for t in targets:
                if t.get("type") == "page" and "chatgpt.com" in t.get("url", ""):
                    self.chatgpt_tab_id = t.get("targetId")
                    print(f"Discovered ChatGPT tab: {self.chatgpt_tab_id}", flush=True)
                    break

            if not self.chatgpt_tab_id:
                print("No active ChatGPT tab found, creating one...", flush=True)
                await self.ws.send(json.dumps({
                    "id": 2,
                    "method": "Target.createTarget",
                    "params": {"url": "https://chatgpt.com"}
                }))
                res = json.loads(await self.ws.recv())
                self.chatgpt_tab_id = res.get("result", {}).get("targetId")
                print(f"Created ChatGPT tab: {self.chatgpt_tab_id}", flush=True)

            return True
        except Exception as e:
            print(f"Failed to connect: {e}", flush=True)
            self.ws = None
            return False

bridge = ChromeCDPBridge()

async def handle_status(request):
    connected = await bridge.ensure_connected()
    return web.json_response({
        "connected": connected,
        "chatgpt_tab": bridge.chatgpt_tab_id
    })

async def init_app():
    app = web.Application()
    app.router.add_get("/status", handle_status)
    return app

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    app = asyncio.run(init_app())
    web.run_app(app, host="127.0.0.1", port=8879)
