import argparse
import random
import httpx
import asyncio
import json, os

from create_key import create_key

KEY_FILE = "loadtest_keys.json"

# each model gets prompts that suit it, so adapter outputs are meaningful under load
PROMPTS = {
    "base": [
        "Say hi.",
        "What is the capital of France?",
        "Explain what a hash function is in two sentences.",
        "Write a short poem about the ocean.",
        "List five tips for writing clean Python code.",
        "Summarize the plot of Romeo and Juliet in one paragraph.",
        "Explain how a TCP handshake works, step by step.",
        "Write a 300-word story about a robot learning to paint.",
    ],
    "sql": [
        "Select all users who signed up in the last 7 days from the users table.",
        "Count the number of orders per customer, highest first.",
        "Find the top 5 products by total revenue using the orders and products tables.",
        "Get the average salary per department, only for departments with more than 10 employees.",
        "List customers who have never placed an order.",
        "Delete all sessions older than 30 days.",
        "Find the second highest salary in the employees table.",
        "Join employees and departments and return each employee's name with their department name.",
    ],
    # Alpaca-style instructions, the kind the adapter was fine-tuned on
    "alpaca": [
        "Give three tips for staying healthy.",
        "Rewrite this sentence in the passive voice: The cat chased the mouse.",
        "Brainstorm five names for a coffee shop.",
        "Classify these animals as mammals or reptiles: snake, dolphin, lizard, bat.",
        "Explain why the sky is blue to a ten-year-old.",
        "Summarize the benefits of regular exercise in three sentences.",
        "Write a haiku about autumn.",
        "Describe the difference between weather and climate.",
    ],
}

async def send_request(client, model, prompt, api_key, max_tokens, stream):
    gateway_URL = f"http://127.0.0.1:8000/models/{model}/chat"

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
            model = random.choice(list(PROMPTS))
            prompt = random.choice(PROMPTS[model])
            _, api_key = random.choice(list(key.items()))
            max_tokens = random.choice([32, 128, 256])
            stream = random.choice([True, False])
            tasks.append(asyncio.create_task(
                send_request(client, model, prompt, api_key, max_tokens, stream)
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
    parser.add_argument("--concurrency", type=int, required=True)
    args = parser.parse_args()
    results = asyncio.run(run(args.concurrency, keys, 0))
   