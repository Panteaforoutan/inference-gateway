import hashlib, psycopg, os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]

SCHEMA = """
    CREATE TABLE IF NOT EXISTS api_keys (
        id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        key_hash    TEXT NOT NULL UNIQUE,
        owner       TEXT NOT NULL,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        revoked     BOOLEAN NOT NULL DEFAULT false
    );

    CREATE TABLE IF NOT EXISTS requests (
        id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        api_key_id      BIGINT NOT NULL REFERENCES api_keys(id),
        started_at      TIMESTAMPTZ NOT NULL,
        model           TEXT,
        status          TEXT NOT NULL,        -- 'ok', 'error', 'client_disconnected'
        tokens_in       INT,
        tokens_out      INT,
        ttft_ms         INT,                  -- time to first token
        total_ms        INT                   -- request arrived -> last token sent
    );

    CREATE INDEX ON requests (api_key_id, started_at);
"""


def get_hash(key):
    return hashlib.sha256(key.encode()).hexdigest()

def get_db():
    return psycopg.connect(DATABASE_URL)
    
def init_db():
    with get_db() as db:
        db.execute(SCHEMA)
    