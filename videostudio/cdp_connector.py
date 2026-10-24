import asyncio
import json
import os
import sys
import time
from pathlib import Path
import websockets

PORT_FILE = Path(os.environ["LOCALAPPDATA"]) / "Google" / "Chrome" / "User Data" / "DevToolsActivePort"
STATUS_FILE = Path(__file__).resolve().parents[1] / "data" / "cdp_status.json"

async def connect_and_monitor():
    if not PORT_FILE.exists():
        print("ERROR: DevToolsActivePort file does not exist", flush=True)
        return False

    lines = PORT_FILE.read_text().splitlines()
    port = lines[0].strip()
    path = lines[1].strip()
    ws_url = f"ws://127.0.0.1:{port}{path}"
    print(f"Connecting to Chrome WebSocket: {ws_url}", flush=True)
    print("Waiting up to 180 seconds for connection / user to click Allow...", flush=True)

    try:
        async with websockets.connect(ws_url, open_timeout=180, ping_interval=20) as ws:
            print(">>> CONNECTED TO CHROME CDP SUCCESSFULLY! <<<", flush=True)
            STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATUS_FILE.write_text(json.dumps({"status": "connected", "port": port, "path": path, "at": time.time()}))

            # Query all targets
            await ws.send(json.dumps({"id": 1, "method": "Target.getTargets"}))
            res = json.loads(await ws.recv())
            targets = res.get("result", {}).get("targetInfos", [])

            chatgpt_target = None
            for t in targets:
                if t.get("type") == "page":
                    print(f"  [Tab] {t.get('title')} -> {t.get('url')}", flush=True)
                    if "chatgpt.com" in t.get("url", ""):
                        chatgpt_target = t

            if not chatgpt_target:
                print("No active chatgpt.com tab found. Opening a new tab for ChatGPT...", flush=True)
                await ws.send(json.dumps({"id": 2, "method": "Target.createTarget", "params": {"url": "https://chatgpt.com"}}))
                res = json.loads(await ws.recv())
                target_id = res.get("result", {}).get("targetId")
                print(f"Created ChatGPT tab with targetId: {target_id}", flush=True)
            else:
                print(f"Found existing ChatGPT tab: {chatgpt_target.get('targetId')}", flush=True)

            print("CDP Client is now ready for VideoStudio jobs!", flush=True)
            return True
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Connection failed or timed out: {type(e).__name__}: {e}", flush=True)
        return False

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    success = asyncio.run(connect_and_monitor())
    sys.exit(0 if success else 1)
