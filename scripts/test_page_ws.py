import asyncio
import json
import os
from pathlib import Path
import websockets

PORT_FILE = Path(os.environ["LOCALAPPDATA"]) / "Google" / "Chrome" / "User Data" / "DevToolsActivePort"

async def test_page_ws():
    lines = PORT_FILE.read_text().splitlines()
    port = lines[0].strip()
    path = lines[1].strip()
    browser_ws = f"ws://127.0.0.1:{port}{path}"

    async with websockets.connect(browser_ws) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Target.getTargets"}))
        res = json.loads(await ws.recv())
        targets = res.get("result", {}).get("targetInfos", [])
        chatgpt = next((t for t in targets if "chatgpt.com" in t.get("url", "")), None)
        target_id = chatgpt["targetId"]

    page_ws_url = f"ws://127.0.0.1:{port}/devtools/page/{target_id}"
    print(f"Connecting directly to Page WebSocket: {page_ws_url}")

    async with websockets.connect(page_ws_url) as page_ws:
        print("Connected to Page WebSocket!")
        check_js = """
        (function() {
            const composer = document.querySelector('#prompt-textarea') || document.querySelector('div[contenteditable="true"]');
            const sendBtn = document.querySelector('button[data-testid="send-button"]') || document.querySelector('button[aria-label="Send prompt"]');
            return {
                has_composer: !!composer,
                composer_id: composer ? composer.id : null,
                has_send: !!sendBtn,
                title: document.title,
                url: location.href
            };
        })()
        """
        await page_ws.send(json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": check_js, "returnByValue": True}
        }))
        eval_res = json.loads(await page_ws.recv())
        val = eval_res.get("result", {}).get("result", {}).get("value")
        print("PAGE DOM RESULT:", json.dumps(val, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(test_page_ws())
