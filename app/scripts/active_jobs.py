import sqlite3, time
from pathlib import Path
p=Path(__file__).resolve().parents[2]/'data/jobs.sqlite3'
if not p.is_file():raise RuntimeError('Cannot establish idle server: database missing')
with sqlite3.connect(p) as c:
    total=c.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running','retrying')").fetchone()[0]
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='scene_image_tasks'").fetchone():
        total+=c.execute("SELECT COUNT(*) FROM scene_image_tasks WHERE state IN ('queued','running')").fetchone()[0]
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='voice_studio_tasks'").fetchone():
        total+=c.execute("SELECT COUNT(*) FROM voice_studio_tasks WHERE state IN ('queued','running')").fetchone()[0]
    if c.execute("SELECT 1 FROM worker_lock WHERE owner LIKE 'voice-clone-%' AND expires>?",(time.time(),)).fetchone():total+=1
    print(total)
