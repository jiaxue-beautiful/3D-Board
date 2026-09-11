"""Durable reservations using GitHub Contents SHA compare-and-swap.

The radar-state branch must be explicitly initialized before use. Never recreate
missing state automatically. Only cost metadata is stored, not keys or prompts.
"""
import base64
from datetime import date
import json
import re
from urllib.request import Request, build_opener
import uuid

from llm import BudgetError, NoRedirect, micros


def github_request(method, url, token, payload):
    req = Request(url, method=method,
                  data=json.dumps(payload).encode() if payload is not None else None,
                  headers={'Authorization': 'Bearer ' + token,
                           'Accept': 'application/vnd.github+json',
                           'Content-Type': 'application/json',
                           'X-GitHub-Api-Version': '2022-11-28',
                           'User-Agent': '3D-Radar/1.0'})
    try:
        with build_opener(NoRedirect).open(req, timeout=25) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError('State too large')
            return json.loads(raw)
    except Exception:
        raise BudgetError('Cloud ledger unavailable or write conflicted; stop without retry') from None


class GitHubStore:
    def __init__(self, repository, token, request=github_request):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository) or not token:
            raise BudgetError('Repository and token required')
        self.url = 'https://api.github.com/repos/' + repository + '/contents/budget.json'
        self.token = token
        self.request = request

    def read(self):
        result = self.request('GET', self.url + '?ref=radar-state', self.token, None)
        try:
            if result['encoding'] != 'base64' or not result['sha']:
                raise ValueError('Invalid state')
            return result['sha'], json.loads(base64.b64decode(result['content']))
        except (KeyError, TypeError, ValueError):
            raise BudgetError('Cloud ledger missing or corrupt; do not reset it') from None

    def write(self, revision, data):
        self.request('PUT', self.url, self.token, {
            'message': 'Record radar budget transaction', 'branch': 'radar-state',
            'sha': revision,
            'content': base64.b64encode(json.dumps(data, separators=(',', ':')).encode()).decode()})


def valid_day(value):
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError('Noncanonical day')
    except (ValueError, TypeError):
        raise BudgetError('Invalid budget day') from None


class CloudBudget:
    def __init__(self, store, daily_limit, request_limit=2):
        self.store = store
        self.limit = micros(daily_limit)
        if type(request_limit) is not int or request_limit < 1:
            raise BudgetError('Invalid request limit')
        self.request_limit = request_limit
        if self.limit > micros(100):
            raise BudgetError('Configured limit exceeds authorized daily USD 100')

    def load(self):
        revision, data = self.store.read()
        if not revision or not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('charges'), list):
            raise BudgetError('Cloud ledger missing or corrupt; do not reset it')
        seen = set()
        for row in data['charges']:
            if (not isinstance(row, dict) or set(row) != {'id', 'day', 'amount', 'status'}
                    or not isinstance(row['id'], str) or not re.fullmatch(r'[a-f0-9]{32}', row['id'])
                    or row['id'] in seen or type(row['amount']) is not int or row['amount'] < 0
                    or row['status'] not in ('pending', 'settled', 'uncertain', 'acknowledged')):
                raise BudgetError('Invalid cloud charge; stop for reconciliation')
            valid_day(row['day'])
            seen.add(row['id'])
        return revision, data

    def reserve(self, day, amount):
        valid_day(day)
        amount = micros(amount)
        revision, data = self.load()
        if any(row['status'] in ('pending', 'uncertain') for row in data['charges']):
            raise BudgetError('Pending or uncertain charge requires reconciliation')
        total = sum(row['amount'] for row in data['charges'] if row['day'] == day)
        calls = sum(1 for row in data['charges'] if row['day'] == day)
        if calls >= self.request_limit:
            raise BudgetError('Daily request limit exhausted; request not sent')
        if total + amount > self.limit:
            raise BudgetError('Daily budget exhausted; request not sent')
        ident = uuid.uuid4().hex
        data['charges'].append({'id': ident, 'day': day, 'amount': amount, 'status': 'pending'})
        self.store.write(revision, data)
        return ident

    def settle(self, ident, amount):
        amount = micros(amount, zero=True)
        revision, data = self.load()
        row = next((r for r in data['charges'] if r['id'] == ident), None)
        if not row or row['status'] != 'pending':
            raise BudgetError('Unknown or already settled reservation')
        exceeded = amount > row['amount']
        row.update(amount=amount, status='uncertain' if exceeded else 'settled')
        self.store.write(revision, data)
        if exceeded:
            raise BudgetError('Gateway charge exceeded reservation; stop and reconcile')

    def uncertain(self, ident):
        revision, data = self.load()
        row = next((r for r in data['charges'] if r['id'] == ident), None)
        if not row or row['status'] != 'pending':
            raise BudgetError('Unknown or already settled reservation')
        row['status'] = 'uncertain'
        self.store.write(revision, data)

    def total(self, day):
        valid_day(day)
        _, data = self.load()
        return sum(r['amount'] for r in data['charges'] if r['day'] == day) / 1000000

    def acknowledge_uncertain(self, ident):
        """Human-authorized risk acceptance, never actual-cost reconciliation.

        Preserve the reservation amount and request count conservatively. This
        method must not be called automatically by collection or scheduled jobs.
        """
        revision, data = self.load()
        row = next((r for r in data['charges'] if r['id'] == ident), None)
        if not row or row['status'] != 'uncertain':
            raise BudgetError('Only an uncertain request may be acknowledged')
        row['status'] = 'acknowledged'
        self.store.write(revision, data)
