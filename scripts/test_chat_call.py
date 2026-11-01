import httpx
import json

def test():
    prompt = "Return exactly this JSON: {\"status\": \"ok\", \"ping\": \"pong\"}"
    print("Calling http://127.0.0.1:8879/api/chat...")
    try:
        r = httpx.post("http://127.0.0.1:8879/api/chat", json={"prompt": prompt}, timeout=120)
        print("Status:", r.status_code)
        print("Body:", r.text)
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    test()
