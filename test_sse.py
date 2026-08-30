import asyncio
import httpx
import time
import threading
import json

async def listen_sse():
    async with httpx.AsyncClient() as client:
        async with client.stream("GET", "http://127.0.0.1:8000/api/stream") as response:
            print(f"SSE connected. Status: {response.status_code}")
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    print(f"SSE received: {line}")
                    if "new_request" in line:
                        print("✅ Success: new_request received via SSE!")
                        break

def trigger_request():
    time.sleep(2)
    print("Triggering simulated request...")
    httpx.post("http://127.0.0.1:8000/v1/chat/completions", 
               json={"model": "gpt-4o", "messages": [{"role": "user", "content": "Test prompt"}]})
               
async def main():
    t = threading.Thread(target=trigger_request)
    t.start()
    
    try:
        await asyncio.wait_for(listen_sse(), timeout=10.0)
    except asyncio.TimeoutError:
        print("❌ Error: Timed out waiting for SSE")

if __name__ == "__main__":
    asyncio.run(main())
