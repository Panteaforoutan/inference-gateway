import datetime
import time
import anyio
import httpx
import os
import json
import scheduler

from fastapi import FastAPI, Header, HTTPException 
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from contextlib import asynccontextmanager
from db import pool, get_hash, log_request
from fastapi.middleware.cors import CORSMiddleware
from scheduler import acquire, release, waiting  


BACKEND_URL = os.environ["BACKEND_URL"]

# llama-server numbers adapters by the order of the --lora flags at launch:
#   llama-server -m base.gguf --lora sql.gguf --lora farsi.gguf --lora-init-without-apply
LORA_IDS = {"sql": 0, "farsi": 1}
MODELS = {"base", *LORA_IDS}

def lora_scales(model_name: str):
    # set every adapter explicitly so a request never inherits another adapter's scale
    return [{"id": i, "scale": 1.0 if name == model_name else 0.0} for name, i in LORA_IDS.items()]

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.client = httpx.AsyncClient(timeout=120)   # 1. startup: create ONE client
    await pool.open()
    yield                                    # 2. server runs here
    await app.state.client.aclose()          # 3. shutdown: close its pool
    await pool.close()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET"],
)

class ChatRequest(BaseModel):
    prompt: str
    max_tokens: int = 256

@app.post("/models/{model_name}/chat")
async def chat(model_name: str, req: ChatRequest, x_api_key: str = Header(), stream: bool = False):
    started_at = datetime.datetime.now(datetime.timezone.utc)   # for the started_at column
    start_time = time.perf_counter()                            # for measuring durations
    model = model_name
    
    api_key_hash = get_hash(x_api_key)
    
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT id FROM api_keys WHERE key_hash = %s AND revoked = false", (api_key_hash,)) # returns None if there are no rows
        row = await cur.fetchone()
    
    if row is None :
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")
    
    api_key_id = row[0]

    if model_name not in MODELS:
        raise HTTPException(status_code=404, detail=f"Unknown model '{model_name}', expected one of {sorted(MODELS)}")

    payload = {
        "messages": [{"role": "user", "content": req.prompt}],
        "max_tokens": req.max_tokens,
        "lora": lora_scales(model_name)
    }
    
    client = app.state.client
    
    handed_off = False
    await acquire()
        
    if stream:
        try: 
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True} 
            
            backend_request = client.build_request("POST", BACKEND_URL, json=payload)
            try:
                response = await client.send(backend_request, stream=True)
            except httpx.RequestError as e:
                total_ms = int((time.perf_counter() - start_time) * 1000)
                await log_request(api_key_id, started_at, model, "error", None, None, None, total_ms)
                raise HTTPException(status_code=502, detail=f"Backend unreachable: {e}")
                

            if response.status_code != 200:
                body = await response.aread()
                await response.aclose()
                total_ms = int((time.perf_counter() - start_time) * 1000)
                await log_request(api_key_id, started_at, model, "error", None, None, None, total_ms)
                raise HTTPException(status_code=502, detail=f"Backend error: {body.decode()}")

            async def body_iterator(): # an async generator, Each time the backend sends a chunk of bytes, it yields that chunk straight through without changing it.
                first_token_at = None 
                got_done = False
                tokens_in = None
                tokens_out = None
                buffer = b""

                try:
                    async for chunk in response.aiter_bytes(): 
                        now = time.perf_counter()
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
                                first_token_at = now 
                            
                            usage = obj.get("usage")
                            if usage:
                                tokens_in = usage["prompt_tokens"]
                                tokens_out = usage["completion_tokens"]
                                
                finally:
                    end_time = time.perf_counter() 
                    release()
                    with anyio.move_on_after(5,shield=True):
                        await response.aclose()
                        status = "ok" if got_done else "error"
                        ttft_ms  = int((first_token_at - start_time) * 1000) if first_token_at else None 
                        total_ms = int((end_time - start_time) * 1000)
                        try: 
                            await log_request(api_key_id, started_at, model, status, tokens_in, tokens_out, ttft_ms, total_ms)
                        except Exception as e:
                            print(f"failed to log request: {e}") 
            handed_off = True               
            return StreamingResponse(body_iterator(), media_type="text/event-stream")
        finally: 
            if not handed_off:
                release()

    try: 
        response = await client.post(BACKEND_URL, json=payload) # while we wait for the backend to reply, the event loop is free to serve other users.
    except httpx.RequestError as e:
        total_ms = int((time.perf_counter() - start_time) * 1000)
        await log_request(api_key_id, started_at, model, "error", None, None, None, total_ms)
        raise HTTPException(status_code=502, detail=f"Backend unreachable: {e}")
    finally:
        release()

    end_time = time.perf_counter() 
    status = "ok" if response.status_code == 200 else "error"
    
    tokens_in = None
    tokens_out = None
    obj = None
    
    if response.status_code == 200:
        obj = response.json()
        usage = obj.get("usage")
        if usage:
            tokens_in = usage["prompt_tokens"]
            tokens_out = usage["completion_tokens"]

    total_ms = int((end_time - start_time) * 1000)
    ttft_ms = total_ms
                            
    await log_request(api_key_id, started_at, model, status, tokens_in, tokens_out, ttft_ms, total_ms)
    
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Backend error: {response.text}")

    return obj



@app.get("/stats")
async def stats():
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT id, api_key_id, started_at, model, status, tokens_in, tokens_out, ttft_ms, total_ms
            FROM requests
            ORDER BY started_at DESC
            LIMIT 20
            """
        )
        cols = [c.name for c in cur.description]
        recent = [dict(zip(cols, row)) for row in await cur.fetchall()]

        # one pass over the last minute; FILTER narrows each aggregate to its own window
        cur = await conn.execute(
            """
            SELECT
                count(*) FILTER (WHERE started_at > now() - interval '10 seconds') / 10.0 AS requests_per_sec,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY ttft_ms) AS p95_ttft_ms,
                count(*) FILTER (WHERE status <> 'ok') AS errors_last_minute
            FROM requests
            WHERE started_at > now() - interval '1 minute'
            """
        )
        requests_per_sec, p95_ttft_ms, errors_last_minute = await cur.fetchone()

    return {
        "recent": recent,
        "requests_per_sec": float(requests_per_sec),
        "p95_ttft_ms": p95_ttft_ms,
        "errors_last_minute": errors_last_minute,
        "in_flight": scheduler.in_flight,
        "waiting": len(waiting)
    }