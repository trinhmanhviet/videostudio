import sqlite3
from pathlib import Path
p=Path(__file__).resolve().parents[1]/'data/jobs.sqlite3'
if not p.is_file():raise RuntimeError('Cannot establish idle server: database missing')
with sqlite3.connect(p) as c:
    total=c.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running','retrying')").fetchone()[0]
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='scene_image_tasks'").fetchone():
        total+=c.execute("SELECT COUNT(*) FROM scene_image_tasks WHERE state IN ('queued','running')").fetchone()[0]
    print(total)
