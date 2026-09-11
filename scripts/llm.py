"""Local guarded adapter for the user's configured OpenAI-compatible gateway.

The SQLite ledger is local, not a distributed or provider-wide billing limit.
Any ambiguous call blocks future work until the ledger is reconciled.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import json
import os
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
import uuid


class BudgetError(Exception):
    pass


class ModelError(Exception):
    pass


def micros(value, zero=False):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or (not zero and number == 0):
            raise BudgetError('Invalid budget amount')
        return int((number * 1000000).to_integral_value(rounding=ROUND_CEILING))
    except (InvalidOperation, ValueError, TypeError):
        raise BudgetError('Invalid budget amount') from None


class Budget:
    def __init__(self, path, daily_limit):
        self.path = Path(path)
        self.limit = micros(daily_limit)
        if self.limit > micros(100):
            raise BudgetError('Configured limit exceeds the authorized daily USD 100')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS charges (id TEXT PRIMARY KEY, day TEXT, amount INTEGER, status TEXT)')
        os.chmod(self.path, 0o600)

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def reserve(self, day, amount):
        amount = micros(amount)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM charges WHERE status != 'settled' LIMIT 1").fetchone():
                raise BudgetError('Pending or uncertain charge requires reconciliation before further calls')
            total = db.execute('SELECT COALESCE(SUM(amount),0) FROM charges WHERE day=?', (day,)).fetchone()[0]
            if total + amount > self.limit:
                raise BudgetError('Daily budget exhausted; request not sent')
            ident = uuid.uuid4().hex
            db.execute('INSERT INTO charges VALUES (?,?,?,?)', (ident, day, amount, 'pending'))
        return ident

    def settle(self, ident, amount):
        amount = micros(amount, zero=True)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT amount,status FROM charges WHERE id=?', (ident,)).fetchone()
            if not row or row[1] != 'pending':
                raise BudgetError('Unknown or already settled reservation')
            exceeded = amount > row[0]
            db.execute('UPDATE charges SET amount=?,status=? WHERE id=?', (amount, 'uncertain' if exceeded else 'settled', ident))
        if exceeded:
            raise BudgetError('Gateway charge exceeded reservation; stop and reconcile')

    def uncertain(self, ident):
        with self.connect() as db:
            db.execute("UPDATE charges SET status='uncertain' WHERE id=?", (ident,))

    def total(self, day):
        with self.connect() as db:
            return db.execute('SELECT COALESCE(SUM(amount),0) FROM charges WHERE day=?', (day,)).fetchone()[0] / 1000000


def endpoint(base):
    u = urlsplit(base)
    if u.scheme != 'https' or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise ValueError('Require an HTTPS gateway URL without credentials or query parameters')
    base = base.rstrip('/')
    return base + ('/chat/completions' if base.endswith('/v1') else '/v1/chat/completions')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def transport(url, key, payload):
    request = Request(url, data=json.dumps(payload, ensure_ascii=False).encode(), headers={
        'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json', 'User-Agent': '3D-Radar/1.0'})
    with build_opener(NoRedirect).open(request, timeout=90) as response:
        raw = response.read(1000001)
        if len(raw) > 1000000:
            raise ModelError('Response exceeds permitted size')
        return json.loads(raw), {k.lower(): v for k, v in response.headers.items()}


def complete(config, budget, messages, send=transport, max_output=1000):
    url = endpoint(config['LLM_BASE_URL'])
    if not config.get('LLM_MODEL') or not config.get('LLM_API_KEY'):
        raise ValueError('Model and API key must be configured')
    if not isinstance(max_output, int) or not 1 <= max_output <= 4000:
        raise ValueError('Output limit must be between 1 and 4000 tokens')
    if not isinstance(messages, list) or not messages or any(not isinstance(m.get('content'), str) or m.get('role') not in ('system','user') for m in messages):
        raise ValueError('Only text system/user messages are supported')
    size = len(json.dumps(messages, ensure_ascii=False).encode())
    if size > 64000:
        raise ValueError('Input exceeds permitted size')
    # Gateway metadata observed 2026-09-10. Reserve conservatively at the largest
    # reported input/cache-write rate; actual billing is accepted only from gateway.
    reserve = ((size + 4096) * 0.0000125 + max_output * 0.00005)
    day = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    ident = budget.reserve(day, reserve)
    payload = {'model':config['LLM_MODEL'], 'messages':messages, 'max_tokens':max_output,
               'stream':False, 'response_format':{'type':'json_object'}, 'num_retries':0,
               'fallbacks':[], 'caching':False}
    try:
        response, headers = send(url, config['LLM_API_KEY'], payload)
    except Exception:
        budget.uncertain(ident)
        raise ModelError('Request failed; no retry. Reserved cost retained pending gateway reconciliation.') from None
    try:
        cost = headers['x-litellm-response-cost']
        micros(cost, zero=True)
        usage = response['usage']
        if any(not isinstance(usage[k], int) or usage[k] < 0 for k in ('prompt_tokens','completion_tokens')):
            raise ValueError('Invalid usage')
    except (KeyError, ValueError, TypeError, BudgetError):
        budget.uncertain(ident)
        raise ModelError('Gateway did not provide reliable cost and usage; stop pending reconciliation.') from None
    budget.settle(ident, cost)
    try:
        choice = response['choices'][0]
        if choice['finish_reason'] != 'stop':
            raise ValueError('Incomplete response')
        content = json.loads(choice['message']['content'])
        if not isinstance(content, dict):
            raise ValueError('Expected JSON object')
    except (KeyError, IndexError, ValueError, TypeError):
        raise ModelError('Response not a complete JSON object; charge recorded, nothing published.') from None
    return {'content':content, 'costUsd':float(cost), 'usage':usage,
            'reservationId':ident, 'day':day}
