import datetime
import time
import httpx
import os
import json

from fastapi import FastAPI, Header, HTTPException 
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from db import get_db, get_hash

BACKEND_URL = os.environ["BACKEND_URL"]

app = FastAPI()

class ChatRequest(BaseModel):
    prompt: str
    max_tokens: int = 256

@app.post("/models/{model_name}/chat")
async def chat(model_name: str, req: ChatRequest, x_api_key: str = Header(), stream: bool = False):
    started_at = datetime.datetime.now(datetime.timezone.utc)   # for the started_at column
    start_time = time.perf_counter()           # for measuring durations
    model = model_name
    
    api_key_hash = get_hash(x_api_key)
    db = get_db()
    row = db.execute("SELECT id FROM api_keys WHERE key_hash = %s AND revoked = false", (api_key_hash,)).fetchone() # returns None if there are no rows
    db.close()
    
    if row is None :
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")
    
    api_key_id = row[0]
    
    payload = {
        "messages": [{"role": "user", "content": req.prompt}],
        "stream": stream,
        "max_tokens": req.max_tokens,
        "stream_options": {"include_usage": True}
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
            first_token_at = None 
            got_done = False
            tokens_in = None
            tokens_out = None
            buffer = b""

            try:
                async for chunk in response.aiter_bytes(): 
                    yield chunk
                    buffer += chunk
                    while b"\n\n" in buffer:
                        event, buffer = buffer.split(b"\n\n", 1) # one full event, rest stays
                        event = event.strip()
                        
                        if not event.startswith(b"data: "):
                            continue
                        
                        data = event[len(b"data: "):]
                        
                        if data == b"[DONE]":
                            got_done = True
                            continue
                        
                        obj = json.loads(data)
                        
                        choices = obj.get("choices") or []
                        if first_token_at is None and choices and choices[0].get("delta", {}).get("content"):
                            first_token_at = time.perf_counter() 
                        
                        usage = obj.get("usage")
                        if usage:
                            tokens_in = usage["prompt_tokens"]
                            tokens_out = usage["completion_tokens"]
                            
            finally:
                end_time = time.perf_counter() 
                
                status = "ok" if got_done else "error"

                ttft_ms  = int((first_token_at - start_time) * 1000) if first_token_at else None 
                total_ms = int((end_time - start_time) * 1000)
                
                db = get_db()
                db.execute("INSERT INTO requests (api_key_id, started_at, model, status, tokens_in, tokens_out, ttft_ms, total_ms) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", (api_key_id, started_at, model, status, tokens_in, tokens_out, ttft_ms, total_ms))
                db.commit()
                db.close()
                
                await client.aclose() 
                await response.aclose()
                

        return StreamingResponse(body_iterator(), media_type="text/event-stream")

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(BACKEND_URL, json=payload)

    end_time = time.perf_counter() 
    
    status = "ok" if resp.status_code == 200 else "error"
    
    tokens_in = None
    tokens_out = None
    obj = None
    
    if resp.status_code == 200:
        obj = resp.json()
        usage = obj.get("usage")
        if usage:
            tokens_in = usage["prompt_tokens"]
            tokens_out = usage["completion_tokens"]

    total_ms = int((end_time - start_time) * 1000)
    ttft_ms = None
                            
    db = get_db()
    db.execute("INSERT INTO requests (api_key_id, started_at, model, status, tokens_in, tokens_out, ttft_ms, total_ms) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", (api_key_id, started_at, model, status, tokens_in, tokens_out, ttft_ms, total_ms))
    db.commit()
    db.close()
    
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Backend error: {resp.text}")

    return obj
