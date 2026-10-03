import argparse
import random
import httpx
import asyncio
import json, os

from create_key import create_key

KEY_FILE = "loadtest_keys.json"

PROMPTS = [
    "Say hi.",
    "What is the capital of France?",
    "Explain what a hash function is in two sentences.",
    "Write a short poem about the ocean.",
    "List five tips for writing clean Python code.",
    "Summarize the plot of Romeo and Juliet in one paragraph.",
    "Explain how a TCP handshake works, step by step.",
    "Write a 300-word story about a robot learning to paint.",
]


gateway_URL = "http://127.0.0.1:8000/models/Qwen2.5-1.5B-Instruct/chat"

async def send_request(client, prompt, api_key, max_tokens, stream):

    payload = {
        "prompt": prompt,
        "max_tokens": max_tokens,
    }

    headers={
        "Content-Type": "application/json", 
        "X-API-Key": api_key
    }

    if not stream:
        response = await client.post(gateway_URL, headers=headers, json=payload)
        return response.status_code

    backend_request = client.build_request("POST", gateway_URL, headers=headers, json=payload, params={"stream": "true"})
    response = await client.send(backend_request, stream=True)
    async for _ in response.aiter_bytes():  # consume the stream so the gateway sees a full request
        pass
    await response.aclose()

    return response.status_code


async def run(n_requests, key, interval):
    async with httpx.AsyncClient(timeout=120) as client:
        tasks = [] 
        for _ in range(n_requests):
            prompt = random.choice(PROMPTS)
            _, api_key = random.choice(list(key.items()))
            max_tokens = random.choice([32, 128, 256])
            stream = random.choice([True, False])
            tasks.append(asyncio.create_task(
                send_request(client, prompt, api_key, max_tokens, stream)
            ))
            await asyncio.sleep(interval)    
        results = await asyncio.gather(*tasks)
    return results 
    
def load_keys(n=10):
    if os.path.exists(KEY_FILE):
        with(open(KEY_FILE)) as f:
            return json.load(f)
        
    keys = {f"loadtest-{i}": create_key(f"loadtest-{i}") for i in range (n)}
    with open(KEY_FILE, "w") as f:
        json.dump(keys, f, indent=2)
    return keys
    
    
if __name__ == "__main__":
    keys = load_keys()
    parser = argparse.ArgumentParser()
    parser.add_argument("--num_requests", type=str, required=True)
    args = parser.parse_args()
    results = asyncio.run(run(int(args.num_requests), keys, 0))
   