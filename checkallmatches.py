import sqlite3

conn = sqlite3.connect("data/state.db")
rows = conn.execute(
    "SELECT raw_name, canonical_name, confidence FROM entity_mapping_log "
    "WHERE confidence > 0 ORDER BY confidence DESC"
).fetchall()
print(f"{len(rows)} total resolved matches (confidence > 0):")
for r in rows:
    print(r)