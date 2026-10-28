"""Persist send intent before browser input; uncertain delivery is read-only recovery.

Text providers are isolated: ChatGPT keeps its original receipt identity, while a
second provider (Gemini) gets a provider-qualified identity and its own
conversation slot so neither can reuse the other's receipt or target.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
from contextlib import contextmanager
from urllib.parse import urlparse


PROVIDERS = ('chatgpt', 'gemini')


class IndeterminateRequest(RuntimeError):
    pass


def valid_chat_url(url):
    p = urlparse(url)
    return p.scheme == 'https' and p.hostname == 'chatgpt.com' and not p.username and not p.password


def valid_gemini_url(url):
    p = urlparse(url)
    return p.scheme == 'https' and p.hostname == 'gemini.google.com' and not p.username and not p.password


def valid_provider_url(provider, url):
    if provider == 'chatgpt':
        return valid_chat_url(url)
    if provider == 'gemini':
        return valid_gemini_url(url)
    raise ValueError('Unknown text provider: '+str(provider))


class RequestJournal:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as c:
            c.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,job TEXT NOT NULL,prompt_hash TEXT NOT NULL,state TEXT NOT NULL,response TEXT);
            CREATE TABLE IF NOT EXISTS conversations(job TEXT PRIMARY KEY,url TEXT NOT NULL,target TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS owned_targets(target TEXT PRIMARY KEY,purpose TEXT NOT NULL);''')

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

    @staticmethod
    def _provider(provider):
        if provider not in PROVIDERS:
            raise ValueError('Unknown text provider: '+str(provider))
        return provider

    @staticmethod
    def _conversation_key(job, provider):
        # Legacy ChatGPT rows keep the bare job key so existing receipts stay valid.
        return job if provider == 'chatgpt' else job+'\0'+provider

    def get(self, identifier):
        with self.db() as c:
            row = c.execute('SELECT * FROM requests WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise KeyError(identifier)
        result = dict(row)
        result['response'] = json.loads(row['response']) if row['response'] is not None else None
        return result

    def prepare(self, job, prompt, provider='chatgpt'):
        provider = self._provider(provider)
        hashed = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
        seed = job+'\0'+hashed if provider == 'chatgpt' else provider+'\0'+job+'\0'+hashed
        identifier = hashlib.sha256(seed.encode()).hexdigest()
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
        res = envelope['result']
        if 'your_response' in res and len(res) == 1 and isinstance(res['your_response'], dict):
            res = res['your_response']
        self.complete(identifier, res)

    def conversation(self, job, provider='chatgpt'):
        provider = self._provider(provider)
        with self.db() as c:
            r = c.execute('SELECT * FROM conversations WHERE job=?', (self._conversation_key(job, provider),)).fetchone()
        return dict(r) if r else None

    def set_conversation(self, job, url, target, provider='chatgpt'):
        provider = self._provider(provider)
        if not valid_provider_url(provider, url):
            raise ValueError('Only exact '+provider+' conversation URLs allowed')
        with self.db() as c:
            c.execute('INSERT OR REPLACE INTO conversations VALUES(?,?,?)', (self._conversation_key(job, provider), url, target))

    def own_target(self,target,purpose):
        if purpose not in ('text','image','gemini'):raise ValueError('Invalid owned target purpose')
        with self.db() as c:c.execute('INSERT OR REPLACE INTO owned_targets VALUES(?,?)',(target,purpose))
    def target_purpose(self,target):
        with self.db() as c:r=c.execute('SELECT purpose FROM owned_targets WHERE target=?',(target,)).fetchone()
        return r['purpose'] if r else None

    def reusable_text_target(self,target,url,provider='chatgpt'):
        provider = self._provider(provider)
        if self.target_purpose(target)!=('text' if provider=='chatgpt' else 'gemini'):return False
        with self.db() as c:r=c.execute('SELECT url FROM conversations WHERE target=? ORDER BY rowid DESC LIMIT 1',(target,)).fetchone()
        if not r:return False
        try:
            return valid_provider_url(provider, r['url']) and r['url'].split('?')[0].rstrip('/')==url.split('?')[0].rstrip('/')
        except ValueError:
            return False
