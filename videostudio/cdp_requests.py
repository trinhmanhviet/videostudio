"""Persist send intent before browser input; uncertain delivery is read-only recovery."""
import hashlib
import json
from pathlib import Path
import sqlite3
from contextlib import contextmanager
from urllib.parse import urlparse


class IndeterminateRequest(RuntimeError):
    pass


def valid_chat_url(url):
    p = urlparse(url)
    return p.scheme == 'https' and p.hostname == 'chatgpt.com' and not p.username and not p.password


class RequestJournal:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as c:
            c.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,job TEXT NOT NULL,prompt_hash TEXT NOT NULL,state TEXT NOT NULL,response TEXT);
            CREATE TABLE IF NOT EXISTS conversations(job TEXT PRIMARY KEY,url TEXT NOT NULL,target TEXT NOT NULL);''')

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def get(self, identifier):
        with self.db() as c:
            row = c.execute('SELECT * FROM requests WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise KeyError(identifier)
        result = dict(row)
        result['response'] = json.loads(row['response']) if row['response'] is not None else None
        return result

    def prepare(self, job, prompt):
        hashed = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
        identifier = hashlib.sha256((job+'\0'+hashed).encode()).hexdigest()
        with self.db() as c:
            c.execute('INSERT OR IGNORE INTO requests VALUES(?,?,?,?,NULL)', (identifier, job, hashed, 'prepared'))
        return self.get(identifier)

    def claim_send(self, identifier):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            count = c.execute("UPDATE requests SET state='sending' WHERE id=? AND state='prepared'", (identifier,)).rowcount
            if count != 1:
                raise IndeterminateRequest('Delivery already attempted; recover matching response, never resubmit')

    def complete(self, identifier, value):
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True)
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT response FROM requests WHERE id=?', (identifier,)).fetchone()
            if row is None:
                raise KeyError(identifier)
            if row['response'] is not None and row['response'] != raw:
                raise ValueError('Immutable response conflict')
            c.execute("UPDATE requests SET state='completed',response=? WHERE id=?", (raw, identifier))

    def accept(self, identifier, envelope):
        if not isinstance(envelope, dict) or envelope.get('request_id') != identifier or not isinstance(envelope.get('result'), dict):
            raise ValueError('Response must match exact request_id and result object')
        self.complete(identifier, envelope['result'])

    def conversation(self, job):
        with self.db() as c:
            r = c.execute('SELECT * FROM conversations WHERE job=?', (job,)).fetchone()
        return dict(r) if r else None

    def set_conversation(self, job, url, target):
        if not valid_chat_url(url):
            raise ValueError('Only exact chatgpt.com conversation URLs allowed')
        with self.db() as c:
            c.execute('INSERT OR REPLACE INTO conversations VALUES(?,?,?)', (job, url, target))
