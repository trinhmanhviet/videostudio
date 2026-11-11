import sqlite3, json

conn = sqlite3.connect("d:/Projects/videostudio/data/jobs.sqlite3")
cur = conn.cursor()
cur.execute("SELECT id, state, stage, error, request FROM jobs WHERE id = '976181bd-ad9f-42c1-ae74-c5e7fe4ab3d0'")
row = cur.fetchone()
if row:
    jid, state, stage, err, req = row
    print("JOB:", jid)
    print("STATE:", state)
    print("STAGE:", stage)
    print("ERROR:", err)
else:
    print("Job not found in data/jobs.sqlite3")
