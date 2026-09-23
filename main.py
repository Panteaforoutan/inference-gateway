# FastAPI server on port 8000 that accepts a chat completion 
# forwards it to it to llama-server on 8080 and streams the response back.

# client request 
# curl -X POST "http://localhost:8000/models/qwen2.5-1.5b-instruct/chat?stream=true" \
#   -H "Content-Type: application/json" \
#   -d '{"prompt": "What is FastAPI?"}'

# gateway request
# curl -X POST "http://localhost:8000/models/qwen2.5-1.5b-instruct/chat" \
#   -d '{"prompt": "What is FastAPI?", "max_tokens": 100}'


# format and send the request to qwen
# curl http://localhost:8080/v1/chat/completions \
#   -H "Content-Type: application/json" \
#   -d '{"messages":[{"role":"user","content":"Explain a queue in one paragraph"}]}' 

import httpx

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

app = FastAPI()

class ChatRequest(BaseModel):
    prompt: str
    max_tokens: int = 256

BACKEND_URL = "http://localhost:8080/v1/chat/completions"


@app.post("/models/{model_name}/chat")
async def chat(model_name: str, req: ChatRequest, stream: bool = False):

    payload = {
        "messages": [{"role": "user", "content": req.prompt}]
    }

    if stream:
        client = httpx.AsyncClient(timeout=120)
        backend_request = client.build_request("POST", BACKEND_URL, json=payload)
        response = await client.send(backend_request, stream=True)  # it opens the connection and gets the response headers, but not the body yet.

        if response.status_code != 200:
            body = await response.aread()
            await client.aclose()
            await response.aclose()
            raise HTTPException(status_code=502, detail=f"Backend error: {body.decode()}")

        async def body_iterator(): # an async generator, Each time the backend sends a chunk of bytes, it yields that chunk straight through without changing it.
            try:
                async for chunk in response.aiter_bytes():
                    yield chunk
            finally:
                await client.aclose() 
                await response.aclose()
                

        return StreamingResponse(body_iterator(), media_type="text/event-stream")

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(BACKEND_URL, json=payload)

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Backend error: {resp.text}")

    return resp.json()
