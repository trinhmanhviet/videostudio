import asyncio
import json
import os
from pathlib import Path
import websockets

PORT_FILE = Path(os.environ["LOCALAPPDATA"]) / "Google" / "Chrome" / "User Data" / "DevToolsActivePort"

async def test_chatgpt_tab():
    lines = PORT_FILE.read_text().splitlines()
    port = lines[0].strip()
    path = lines[1].strip()
    browser_ws = f"ws://127.0.0.1:{port}{path}"

    async with websockets.connect(browser_ws) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Target.getTargets"}))
        res = json.loads(await ws.recv())
        targets = res.get("result", {}).get("targetInfos", [])

        chatgpt = next((t for t in targets if "chatgpt.com" in t.get("url", "")), None)
        if not chatgpt:
            print("No ChatGPT tab found!")
            return

        print(f"Attaching to ChatGPT tab: {chatgpt['targetId']} ({chatgpt['url']})")
        # Attach to page target
        await ws.send(json.dumps({
            "id": 2,
            "method": "Target.attachToTarget",
            "params": {"targetId": chatgpt["targetId"], "flatten": True}
        }))
        attach_res = json.loads(await ws.recv())
        session_id = attach_res.get("result", {}).get("sessionId")
        print(f"Attached with sessionId: {session_id}")

        # Evaluate JavaScript to check the composer element
        check_js = """
        (function() {
            const composer = document.querySelector('#prompt-textarea') || document.querySelector('div[contenteditable="true"]');
            const sendBtn = document.querySelector('button[data-testid="send-button"]') || document.querySelector('button[aria-label="Send prompt"]');
            return {
                has_composer: !!composer,
                composer_tag: composer ? composer.tagName : null,
                has_send: !!sendBtn,
                title: document.title
            };
        })()
        """
        await ws.send(json.dumps({
            "id": 3,
            "sessionId": session_id,
            "method": "Runtime.evaluate",
            "params": {"expression": check_js, "returnByValue": True}
        }))
        eval_res = json.loads(await ws.recv())
        result_value = eval_res.get("result", {}).get("result", {}).get("value")
        print("DOM Check on ChatGPT tab:", json.dumps(result_value, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(test_chatgpt_tab())
