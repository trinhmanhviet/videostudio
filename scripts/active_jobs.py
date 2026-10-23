import sqlite3
from pathlib import Path
p=Path(__file__).resolve().parents[1]/'data/jobs.sqlite3'
if not p.is_file():raise RuntimeError('Cannot establish idle server: database missing')
with sqlite3.connect(p) as c:
    print(c.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running','retrying')").fetchone()[0])
