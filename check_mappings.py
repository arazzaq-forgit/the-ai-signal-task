import sqlite3

conn = sqlite3.connect("data/state.db")
rows = conn.execute(
    "SELECT raw_name, canonical_name, confidence FROM entity_mapping_log "
    "WHERE canonical_name != raw_name ORDER BY confidence ASC LIMIT 40"
).fetchall()
for r in rows:
    print(r)