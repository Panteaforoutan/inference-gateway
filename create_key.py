# 1. Generates a random key.
# 2. Hashes it.
# 3. Connects to the same database your gateway uses and inserts a row: (hash, owner=”sara”, created_at=”now” revoked=”false”).
# 4. Prints the key to your terminal once.
import secrets, argparse
from db import get_db, get_hash

def create_key(owner):
    key = "pgw_" + secrets.token_urlsafe(32)
    key_hash = get_hash(key)
    
    db = get_db()
    
    # revoke the owner's previous active keys before adding the new one
    # (if the owner has no keys yet, this matches no rows and does nothing)
    db.execute("UPDATE api_keys SET revoked = true WHERE owner = %s AND revoked = false", (owner,))
    db.execute("INSERT INTO api_keys (key_hash, owner) VALUES (%s, %s)", (key_hash, owner))
    db.commit()
    db.close()

    return key


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", type=str, required=True)
    args = parser.parse_args()

    key = create_key(args.owner)
    print(f"Key for {args.owner}: {key}")
