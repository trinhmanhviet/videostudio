"""Small creative-history ledger in the existing Store database.

Call ``record(..., 'rendered')`` only after the actual render verification passes.
Publishing is always an explicit caller action; a completed job implies neither.
Human feedback is optional, rated 1..5 (or None for a note only), and writable
only through ``feedback``. Metadata is a JSON object; partial updates preserve
previous top-level fields. Useful fields include idea, theme, characters,
motivation, misunderstanding, techniques, props, climax, ending, catchphrases,
callbacks, and critic. History informs variety; it does not prohibit reuse.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
import math
from pathlib import Path
import time

__all__ = ['load_playbook', 'record', 'recent', 'feedback']

STATUSES = ('draft', 'reviewed', 'approved', 'rendered', 'published', 'rejected')
_RANK = {status: rank for rank, status in enumerate(STATUSES[:-1])}


def load_playbook():
    """Return an independent copy of the versioned shared writing configuration."""
    return json.loads(Path(__file__).with_name('comedy_playbook.json').read_text(encoding='utf-8'))


def _job_id(job):
    value = job.get('id') if isinstance(job, Mapping) else job
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Comedy memory requires a non-empty job id')
    return value


def _ensure_table(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS comedy_memory(
        job TEXT PRIMARY KEY,
        metadata TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL CHECK(status IN ('draft','reviewed','approved','rendered','published','rejected')),
        human_rating REAL,
        human_note TEXT,
        feedback_at REAL,
        rendered INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    )''')
    if 'rendered' not in {r['name'] for r in connection.execute('PRAGMA table_info(comedy_memory)')}:
        connection.execute('ALTER TABLE comedy_memory ADD COLUMN rendered INTEGER NOT NULL DEFAULT 0')


def _summary(row):
    return {
        'job': row['job'],
        'status': row['status'],
        'metadata': json.loads(row['metadata']),
        'rendered': bool(row['rendered']) or row['status'] in ('rendered', 'published'),
        'published': row['status'] == 'published',
        'human_feedback': None if row['feedback_at'] is None else {
            'rating': row['human_rating'], 'note': row['human_note'], 'at': row['feedback_at']},
        'created_at': row['created_at'],
        'updated_at': row['updated_at'],
    }


def record(store, job, metadata, status):
    """Idempotently merge metadata and record an explicit creative lifecycle state.

    Retried earlier stages do not demote reviewed/approved/rendered/published
    work. Rejection is preserved on draft replay; an explicit review, approval,
    render, or publication can reopen it. Published entries stay published.
    Render verification remains the caller's responsibility.
    """
    job_id = _job_id(job)
    if status not in STATUSES:
        raise ValueError('Unknown comedy memory status')
    if not isinstance(metadata, Mapping):
        raise ValueError('Comedy memory metadata must be a JSON object')
    # Human judgment cannot be silently rewritten by generated metadata.
    incoming = {key: value for key, value in metadata.items() if key != 'human_feedback'}
    raw = json.dumps(incoming, ensure_ascii=False, sort_keys=True, allow_nan=False)
    incoming = json.loads(raw)
    with store.db() as connection:
        connection.execute('BEGIN IMMEDIATE')
        _ensure_table(connection)
        row = connection.execute('SELECT * FROM comedy_memory WHERE job=?', (job_id,)).fetchone()
        now = time.time()
        if row is None:
            connection.execute('INSERT INTO comedy_memory(job,metadata,status,created_at,updated_at,rendered) VALUES(?,?,?,?,?,?)',
                               (job_id, raw, status, now, now, int(status in ('rendered','published'))))
        else:
            previous = row['status']
            stale = ((previous=='published' and status!='published') or
                     (previous=='rejected' and status=='draft') or
                     (previous in _RANK and status in _RANK and _RANK[status]<_RANK[previous]))
            rendered = bool(row['rendered']) or previous in ('rendered','published') or status in ('rendered','published')
            if previous == 'published' or (previous == 'rejected' and status == 'draft'):
                status = previous
            elif previous in _RANK and status in _RANK:
                status = max((previous, status), key=_RANK.__getitem__)
            merged = json.loads(row['metadata'])
            if not stale:merged.update(incoming)
            raw = json.dumps(merged, ensure_ascii=False, sort_keys=True, allow_nan=False)
            if raw != row['metadata'] or status != previous or rendered != bool(row['rendered']):
                connection.execute('UPDATE comedy_memory SET metadata=?,status=?,updated_at=?,rendered=? WHERE job=?',
                                   (raw, status, now, int(rendered), job_id))
        return _summary(connection.execute('SELECT * FROM comedy_memory WHERE job=?', (job_id,)).fetchone())


def recent(store, limit=12):
    """Return newest summaries, including clearly labeled rejected/draft entries.

    No job state is consulted or converted into publication. Use the explicit
    status/rendered/published fields when comparing produced episodes.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError('Comedy memory limit must be a non-negative integer')
    with store.db() as connection:
        connection.execute('BEGIN IMMEDIATE')
        _ensure_table(connection)
        rows = connection.execute('SELECT * FROM comedy_memory ORDER BY updated_at DESC,job DESC LIMIT ?',
                                  (limit,)).fetchall()
        return [_summary(row) for row in rows]


def feedback(store, job, rating, note=''):
    """Record optional human feedback without changing creative lifecycle state."""
    job_id = _job_id(job)
    if rating is not None and (isinstance(rating, bool) or not isinstance(rating, (int, float))
                               or not math.isfinite(rating) or not 1 <= rating <= 5):
        raise ValueError('Human rating must be between 1 and 5, or None')
    if not isinstance(note, str):
        raise ValueError('Human feedback note must be text')
    with store.db() as connection:
        connection.execute('BEGIN IMMEDIATE')
        _ensure_table(connection)
        row = connection.execute('SELECT * FROM comedy_memory WHERE job=?', (job_id,)).fetchone()
        if row is None:
            raise ValueError('Record the comedy job before adding feedback')
        if row['human_rating'] != rating or row['human_note'] != note or row['feedback_at'] is None:
            now = time.time()
            connection.execute('UPDATE comedy_memory SET human_rating=?,human_note=?,feedback_at=?,updated_at=? WHERE job=?',
                               (rating, note, now, now, job_id))
        return _summary(connection.execute('SELECT * FROM comedy_memory WHERE job=?', (job_id,)).fetchone())
