# 1. Generates a random key.
# 2. Hashes it.
# 3. Connects to the same database your gateway uses and inserts a row: (hash, owner=”sara”, created_at=”now” revoked=”false”).
# 4. Prints the key to your terminal once.
import secrets, sys, hashlib, sqlite3, argparse
from db import get_db
   
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", type=str)
    args = parser.parse_args()
    
    # owner = sys.argv[2]
    owner = args.owner
    key = "pgw_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    
    db = get_db()
    
    # revoke the owner's previous active keys before adding the new one
    # (if the owner has no keys yet, this matches no rows and does nothing)
    db.execute("UPDATE api_keys SET revoked = 1 WHERE owner = ? AND revoked = 0", (owner,))
    db.execute("INSERT INTO api_keys (key_hash, owner) VALUES (?, ?)", (key_hash, owner))
    db.commit()
    db.close()
    
    print(f"Key for {owner}: {key}") 
    

if __name__ == "__main__":
    main()
