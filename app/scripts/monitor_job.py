import sqlite3, time, datetime, sys

sys.stdout.reconfigure(encoding='utf-8')
job_id = sys.argv[1] if len(sys.argv) > 1 else 'f9d386c3-ffef-4121-9e98-0b9caf4c4ddf'
last_stage = ''
last_detail = ''

print(f"Monitoring started for job {job_id} at {datetime.datetime.now().strftime('%H:%M:%S')}", flush=True)

for _ in range(720):  # up to 4 hours (20s interval)
    time.sleep(20)
    try:
        with sqlite3.connect((__import__('pathlib').Path(__file__).resolve().parents[2]/'data/jobs.sqlite3').as_uri()+'?mode=ro', uri=True) as c:
            c.row_factory = sqlite3.Row
            r = c.execute('SELECT state, stage, error, output FROM jobs WHERE id=?', (job_id,)).fetchone()
            e = c.execute('SELECT stage, event, detail FROM events WHERE job=? ORDER BY seq DESC LIMIT 1', (job_id,)).fetchone()
    except Exception as ex:
        print('DB_READ_ERR:', ex, flush=True)
        continue

    if not r:
        print('JOB_NOT_FOUND', job_id, flush=True)
        sys.exit(1)

    stage = r['stage'] or ''
    state = r['state'] or ''
    detail = (e['detail'] if e else '') or ''

    now_str = datetime.datetime.now().strftime('%H:%M:%S')
    if stage != last_stage or detail != last_detail:
        print(f"[{now_str}] Stage: {stage} | State: {state} | Detail: {detail[:100]}", flush=True)
        last_stage = stage
        last_detail = detail

    if state == 'completed':
        print(f"[{now_str}] JOB_FINISHED_SUCCESS: {r['output']}", flush=True)
        sys.exit(0)

    if state == 'failed':
        print(f"[{now_str}] JOB_FINISHED_FAILURE in stage '{stage}': {r['error']}", flush=True)
        sys.exit(1)

print('TIMEOUT_MONITORING', flush=True)
sys.exit(2)
