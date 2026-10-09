# inference-gateway

A gateway that sits between clients and a locally hosted LLM server. It authenticates requests with API keys, queues them, picks the right LoRA adapter for the requested model, and logs every request so you can watch traffic live on a dashboard.

Clients never talk to the model server directly. That gives one place to control access, limit how much work hits the model at once, and measure latency.

## How it works

```
client ──► gateway (FastAPI) ──► llama-server (Qwen 2.5 1.5B + LoRA adapters)
              │
              ├─ checks the API key against Postgres
              ├─ waits for a free slot (max 4 in flight, FIFO queue)
              ├─ sets adapter scales for the requested model
              └─ logs the request (tokens, TTFT, total time) to Postgres
                        │
dashboard (React) ◄── GET /stats (polled every second)
```

1. The client sends `POST /models/{model_name}/chat` with an `X-API-Key` header.
2. The gateway hashes the key and looks it up in Postgres. Unknown or revoked keys get `401`.
3. The request waits for one of 4 slots, matching llama-server's 4 parallel slots. Extra requests wait in a first-in-first-out queue.
4. The gateway forwards the prompt to llama-server, turning on the adapter for `model_name` and turning the others off.
5. The response is returned whole, or streamed back as server-sent events if `?stream=true`.
6. Tokens in/out, time to first token (TTFT) and total time are written to the `requests` table.

## Features

- API key authentication (keys are stored as SHA-256 hashes, never in plain text)
- Per-request LoRA adapter switching on a single model server, with no reloads
- Streaming and non-streaming responses
- Concurrency limit with a FIFO queue so the model server isn't overloaded
- Request logging to Postgres
- Live dashboard: requests/sec, p95 TTFT, errors in the last minute, in-flight and queued requests, recent requests
- Load tester that sends concurrent requests across all models

## Models

Base model: **Qwen 2.5 1.5B Instruct** (GGUF, Q4_K_M), served by llama.cpp's `llama-server`.

| `model_name` | What it does                                                                 |
| ------------ | ---------------------------------------------------------------------------- |
| `base`       | The base model, no adapter                                                   |
| `sql`        | Base model + a LoRA adapter fine-tuned to write SQL for a given table schema |
| `alpaca`     | Base model + a LoRA adapter fine-tuned on general English instructions       |

Both adapters are loaded once when llama-server starts. Each request sets every adapter's scale (`1.0` for the requested one, `0.0` for the rest), so switching models costs nothing. Any other `model_name` returns `404`.

Qwen 2.5 is multilingual, so the base model already understands and answers in languages like Farsi without an adapter.

### Training the adapters

Both adapters were trained in Google Colab on top of Qwen 2.5 1.5B Instruct:

- `sql`: [`b-mc2/sql-create-context`](https://huggingface.co/datasets/b-mc2/sql-create-context), where each example pairs a question and a `CREATE TABLE` schema with the SQL answer.
- `alpaca`: the first 1,000 rows of [`yahma/alpaca-cleaned`](https://huggingface.co/datasets/yahma/alpaca-cleaned), a cleaned version of Stanford's English instruction dataset. Each row is formatted with Qwen's chat template as a user/assistant pair.

The trained adapters were converted to GGUF with llama.cpp's `convert_lora_to_gguf.py` so `llama-server` can load them.

<!-- TODO: training library (PEFT / Unsloth), LoRA rank and alpha, epochs or steps -->

## Setup

Requirements: Python 3.11+, Node.js, Docker, and [llama.cpp](https://github.com/ggml-org/llama.cpp) (`llama-server`). You also need the two adapters as GGUF files.

1. Install Python dependencies:

   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Create a Postgres container (once):

   ```bash
   docker run --name pg -e POSTGRES_PASSWORD=<password> -p 5432:5432 -d postgres
   ```

3. Copy `.env.example` to `.env` and fill it in:

   ```bash
   DATABASE_URL=postgresql://postgres:<password>@localhost:5432/postgres
   BACKEND_URL=http://localhost:8080/v1/chat/completions
   ```

4. Create the tables (once):

   ```bash
   python -c "from db import init_db; init_db()"
   ```

5. Create an API key. It is printed once, so save it:

   ```bash
   python create_key.py --owner <name>
   ```

6. Install the dashboard dependencies:

   ```bash
   cd dashboard-ui && npm install
   ```

## Running

1. Start Docker and Postgres:

   ```bash
   open -a Docker
   docker start pg
   ```

2. Start the model server with both adapters. The order of the `--lora` flags matters: `sql` must be first (id 0) and `alpaca` second (id 1).

   ```bash
   llama-server -hf Qwen/Qwen2.5-1.5B-Instruct-GGUF:Q4_K_M \
     --lora <path-to>/sql-lora.gguf \
     --lora <path-to>/alpaca-lora.gguf \
     --lora-init-without-apply \
     --port 8080
   ```

3. Start the gateway (port 8000):

   ```bash
   fastapi dev main.py
   ```

4. Start the dashboard (http://localhost:5173):

   ```bash
   cd dashboard-ui && npm run dev
   ```

## Usage

Non-streaming request to the `alpaca` adapter:

```bash
curl -X POST "http://localhost:8000/models/alpaca/chat" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <your-key>" \
  -d '{"prompt": "Give three tips for staying healthy.", "max_tokens": 150}'
```

The response is llama-server's OpenAI-style chat completion, passed through (shortened):

```json
{
  "choices": [{ "message": { "role": "assistant", "content": "..." } }],
  "usage": { "prompt_tokens": 32, "completion_tokens": 150 }
}
```

Streaming request to the base model:

```bash
curl -N -X POST "http://localhost:8000/models/base/chat?stream=true" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <your-key>" \
  -d '{"prompt": "What is FastAPI?", "max_tokens": 100}'
```

Request body: `prompt` (required) and `max_tokens` (optional, default 256).

## Load testing

```bash
python load_tester.py --concurrency 50
```

This sends 50 requests at once. For each request it picks a random model (`base`, `sql` or `alpaca`), a prompt suited to that model, a random API key, a random `max_tokens` (32, 128 or 256), and streaming or non-streaming at random. On the first run it creates 10 API keys and saves them to `loadtest_keys.json`.

The gateway lets 4 requests through at a time and queues the rest, so even large bursts complete. Watch the dashboard while it runs to see the queue fill and drain.


## Design decisions

- **Concurrency limit of 4 with a FIFO queue.** This matches llama-server's 4 slots, so waiting happens in the gateway, where it can be measured.
- **One shared `httpx.AsyncClient`.** Connections to llama-server are reused instead of opened for every request.
- **All adapters on one server.** Switching is done per request with adapter scales, not by running one server per model.
- **TTFT for non-streaming requests = total time.** The client gets nothing until the whole response is ready.

The full reasoning is in [DESIGN.md](docs/DESIGN.md).

## Limitations / future work

- No per-user rate limits yet. The plan is to track tokens per key, return `429` when a user is over their limit, and replace the FIFO queue with a scheduler that favours light users and short requests.
- The slot limit (4) and the adapter list are hardcoded. Adding an adapter means editing `main.py` and restarting llama-server.
- Runs on a single machine with a single model server.
