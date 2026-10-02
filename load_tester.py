import httpx

gateway_URL = "http://127.0.0.1:8000/models/Qwen2.5-1.5B-Instruct/chat"

def send_request(prompt, max_tokens, api_key, stream=False):

    payload = {
        "prompt": prompt,
        "max_tokens": max_tokens,
    }

    headers={
        "Content-Type": "application/json", 
        "X-API-Key": api_key
    }

    if not stream:
        with httpx.Client(timeout=120) as client:
            response = client.post(gateway_URL, headers=headers, json=payload)
        return response.status_code

    with httpx.Client(timeout=120) as client:
        backend_request = client.build_request("POST", gateway_URL, headers=headers, json=payload, params={"stream": "true"})
        response = client.send(backend_request, stream=True)
        for _ in response.iter_bytes():  # consume the stream so the gateway sees a full request
            pass
        response.close()

    return response.status_code
