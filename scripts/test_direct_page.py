import asyncio
import json
import websockets

async def test_page():
    # ChatGPT target ID discovered from tabs
    target_id = "B5409DADF32DA31434F8D224AFD3606E"
    ws_url = f"ws://127.0.0.1:9222/devtools/page/{target_id}"
    print(f"Connecting to page WS: {ws_url}", flush=True)

    # Passing origin=None in websockets.connect prevents sending an Origin header
    async with websockets.connect(ws_url, open_timeout=5, origin=None) as ws:
        print("Connected to Page WS!", flush=True)
        eval_expr = "document.title"
        await ws.send(json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": eval_expr, "returnByValue": True}
        }))
        res = json.loads(await ws.recv())
        title = res.get("result", {}).get("result", {}).get("value")
        print(f"Title from Page WS: {title}", flush=True)

if __name__ == "__main__":
    asyncio.run(test_page())
