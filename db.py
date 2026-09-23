import sqlite3

DB_PATH = "gateway.db"

def get_db():
    db =  sqlite3.connect(DB_PATH)
    db.execute(""" 
               CREATE TABLE IF NOT EXISTS api_keys (
                   key_hash     TEXT PRIMARY KEY, 
                   owner        TEXT NOT NULL,
                   created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   revoked      NOT NULL DEFAULT 0
                )
    """)
    
    return db