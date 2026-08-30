import sqlite3
import json
conn = sqlite3.connect("../controlplane.db")
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT id, policy_matrix FROM policies").fetchall()
for r in rows:
    print(r["id"], r["policy_matrix"])
