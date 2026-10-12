"""Open shared coordination: expiring work leases and durable outbound fences.

Standard library only. No credentials or message bodies in the database.
"""
import hashlib
import json
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


FACETS = {
    'identity': ['auth', 'authentication', 'login', 'signin', 'sign in', 'oauth', 'session'],
    'payments': ['payment', 'billing', 'checkout', 'invoice', 'stripe'],
    'interface': ['ui', 'frontend', 'screen', 'layout', 'design'],
    'storage': ['database', 'schema', 'sql', 'storage', 'persistence'],
    'performance': ['performance', 'latency', 'speed', 'optimization', 'cache'],
    'documentation': ['docs', 'documentation', 'readme', 'guide'],
    'outreach': ['email', 'reply', 'contact', 'outreach', 'send', 'proposal'],
}

def canonical(value):
    value = str(value).strip().lower().rstrip('/')
    value = re.sub(r'^https?://(?:www\.)?', '', value)
    value = re.sub(r'\.git$', '', value)
    return value

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),ensure_ascii=False).encode()).hexdigest()

def scope(value):
    entity = canonical(value.get('entity', ''))
    if not entity:
        raise ValueError('canonical entity is required; use provider identity, repository URL or deal ID')
    text = value.get('description', '').lower()
    facets = set(value.get('facets', []))
    for facet, words in FACETS.items():
        if any(re.search(r'\b' + re.escape(word) + r'\b', text) for word in words):
            facets.add(facet)
    return {'entity': entity, 'kind': value.get('kind', 'engineering'),
            'resources': sorted({canonical(x) for x in value.get('resources', [])}),
            'facets': sorted(facets), 'description': value.get('description', '')}

def overlap(a, b):
    if a['entity'] != b['entity']:
        return None
    if a['kind'] == 'read' or b['kind'] == 'read':
        return None
    ar, br = a['resources'], b['resources']
    paths = any(x == y or x.startswith(y + '/') or y.startswith(x + '/') for x in ar for y in br)
    if a['kind'] != b['kind'] and not paths:
        return None
    common = set(a['facets']) & set(b['facets'])
    if paths or common:
        return {'reason': 'shared resource' if paths else 'shared contribution facet', 'facets': sorted(common)}
    if ar and br:
        return None
    if a['facets'] and b['facets']:
        return None
    return {'reason': 'ambiguous scope on same entity; supply exact resources or facets', 'ambiguous': True}


class Coordinator:
    def __init__(self, path, clock=time.time):
        self.path, self.clock = str(path), clock
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS leases(id TEXT PRIMARY KEY, owner TEXT, scope TEXT,
                until REAL, state TEXT, version INTEGER DEFAULT 1);
            CREATE TABLE IF NOT EXISTS sends(id TEXT PRIMARY KEY, fence TEXT UNIQUE,
                binding TEXT, state TEXT, receipt TEXT, version INTEGER DEFAULT 1);
            CREATE TABLE IF NOT EXISTS events(n INTEGER PRIMARY KEY, at REAL, type TEXT, object TEXT, data TEXT);
            CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, state TEXT);
            CREATE TABLE IF NOT EXISTS observations(id TEXT PRIMARY KEY, source TEXT, observed REAL, data TEXT);
            ''')

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=FULL')
        db.execute('BEGIN IMMEDIATE')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def event(self, db, kind, object_id, data):
        db.execute('INSERT INTO events(at,type,object,data) VALUES(?,?,?,?)',
                   (self.clock(), kind, object_id, json.dumps(data)))

    def take(self, request):
        item = scope(request)
        oid, owner = request['operation_id'], request['owner']
        ttl = max(30, min(1800, int(request.get('ttl_seconds', 300))))
        with self.transaction() as db:
            prior = db.execute('SELECT * FROM leases WHERE id=?', (oid,)).fetchone()
            if prior and (json.loads(prior['scope']) != item or prior['owner'] != owner):
                raise ValueError('operation ID already bound to different work')
            conflicts = []
            for row in db.execute("SELECT * FROM leases WHERE state='ACTIVE' AND until>? AND id!=?", (self.clock(), oid)):
                match = overlap(item, json.loads(row['scope']))
                if match:
                    conflicts.append({'operation_id': row['id'], 'owner': row['owner'], 'until': row['until'], **match})
            definite=[c for c in conflicts if not c.get('ambiguous')]
            if definite:
                used = {f for c in conflicts for f in c.get('facets', [])}
                return {'decision': 'CHOOSE_DIFFERENT_ANGLE', 'conflicts': definite,
                        'message': 'Please choose a different angle of contribution or engineering for this claim, or choose another.',
                        'alternatives': [f for f in FACETS if f not in used and f != 'outreach'],
                        'send_authorized': False}
            db.execute('INSERT INTO leases(id,owner,scope,until,state) VALUES(?,?,?,?,?) '
                       'ON CONFLICT(id) DO UPDATE SET until=excluded.until,state=excluded.state,version=leases.version+1',
                       (oid, owner, json.dumps(item), self.clock() + ttl, 'ACTIVE'))
            self.event(db, 'take', oid, item)
            return {'decision': 'TAKEN_WITH_SCOPE_ADVICE' if conflicts else 'TAKEN', 'scope_advice': conflicts,
                    'operation_id': oid, 'until': self.clock() + ttl, 'send_authorized': False}

    def progress(self, request):
        with self.transaction() as db:
            row = db.execute('SELECT * FROM leases WHERE id=?', (request['operation_id'],)).fetchone()
            if not row or row['owner'] != request['owner']:
                raise ValueError('lease owner mismatch or unknown lease')
            state = request.get('state', 'ACTIVE')
            if state not in ('ACTIVE', 'DONE', 'RELEASED'):
                raise ValueError('invalid planning state')
            if state == 'ACTIVE' and row['until'] <= self.clock():
                return {'decision': 'RETAKE_REQUIRED', 'send_authorized': False}
            until = self.clock() + max(30, min(1800, int(request.get('ttl_seconds', 300))))
            db.execute('UPDATE leases SET until=?,state=?,version=version+1 WHERE id=?', (until, state, row['id']))
            self.event(db, 'progress', row['id'], {'state': state, 'progress': request.get('progress', '')})
            return {'decision': state, 'until': until, 'send_authorized': False}

    def reserve(self, request):
        # Account/wording NEVER splits the conversation fence. Exact provider IDs required.
        for key in ('operation_id', 'provider', 'conversation_id', 'action', 'payload_hash', 'source_version', 'actor'):
            if not request.get(key):
                raise ValueError('missing outbound binding: ' + key)
        fence = digest([canonical(request['provider']), str(request['conversation_id']), request['action']])
        binding = {key: request[key] for key in ('provider', 'conversation_id', 'action', 'payload_hash', 'source_version', 'actor')}
        with self.transaction() as db:
            prior = db.execute('SELECT * FROM sends WHERE fence=? OR id=?', (fence, request['operation_id'])).fetchall()
            if prior:
                row = prior[0]
                if row['id'] == request['operation_id'] and json.loads(row['binding']) == binding:
                    return {'decision': 'ALREADY_RESERVED', 'state': row['state'], 'operation_id': row['id'], 'send_authorized': False}
                return {'decision': 'DO_NOT_SEND', 'state': row['state'], 'operation_id': row['id'],
                        'message': 'This conversation/action already has an outbound reservation. Reconcile its provider outcome.', 'send_authorized': False}
            db.execute('INSERT INTO sends(id,fence,binding,state) VALUES(?,?,?,?)',
                       (request['operation_id'], fence, json.dumps(binding), 'RESERVED'))
            self.event(db, 'reserved', request['operation_id'], binding)
            return {'decision': 'RESERVED', 'operation_id': request['operation_id'], 'send_authorized': False}

    def transition(self, oid, before, after, receipt=None, binding=None):
        with self.transaction() as db:
            row = db.execute('SELECT * FROM sends WHERE id=?', (oid,)).fetchone()
            if not row or row['state'] != before or (binding is not None and json.loads(row['binding']) != binding):
                raise ValueError('outbound state or payload/source/actor fence changed')
            db.execute('UPDATE sends SET state=?,receipt=?,version=version+1 WHERE id=?', (after, json.dumps(receipt), oid))
            self.event(db, after, oid, receipt or {})

    def dispatch(self, request, send, readback):
        """One winner calls provider. Failure/unknown effect retains permanent fence.

        Adapter must verify actor and read back exact provider message before SENT.
        """
        result = self.reserve(request)
        if result['decision'] != 'RESERVED':
            return result
        binding = {key: request[key] for key in ('provider', 'conversation_id', 'action', 'payload_hash', 'source_version', 'actor')}
        self.transition(request['operation_id'], 'RESERVED', 'DISPATCHED', binding=binding)
        try:
            effect = send(request)
            receipt = readback(effect, request)
            if not receipt or receipt.get('verified') is not True or receipt.get('actor') != request['actor'] or not receipt.get('provider_id'):
                raise ValueError('provider readback incomplete')
            self.transition(request['operation_id'], 'DISPATCHED', 'SENT', receipt)
            return {'decision': 'SENT', 'receipt': receipt}
        except BaseException:
            self.transition(request['operation_id'], 'DISPATCHED', 'UNKNOWN_EFFECT')
            raise

    def snapshot(self):
        with self.transaction() as db:
            return {'leases': [dict(r) | {'scope': json.loads(r['scope']), 'effective_state': r['state'] if r['until'] > self.clock() else 'STALE'} for r in db.execute('SELECT * FROM leases')],
                    'outbound': [dict(r) | {'binding': json.loads(r['binding'])} for r in db.execute('SELECT * FROM sends')],
                    'sources': [dict(r) for r in db.execute('SELECT * FROM sources')]}

    def reconcile(self, request, reader):
        """Only provider-specific reader can release known-no-effect or mark SENT.

        Caller assertion never clears a dispatched/unknown fence.
        """
        with self.transaction() as db:
            row = db.execute('SELECT * FROM sends WHERE id=?', (request['operation_id'],)).fetchone()
            if not row:
                raise ValueError('unknown operation')
            state, binding = row['state'], json.loads(row['binding'])
        evidence = reader(binding)
        if evidence.get('verified') is not True:
            return {'decision': 'DO_NOT_SEND', 'state': state}
        if evidence.get('provider_id') and evidence.get('actor') == binding['actor']:
            self.transition(row['id'], state, 'SENT', evidence)
            return {'decision': 'SENT', 'receipt': evidence}
        # Absence from a list/search is not proof of no effect. Keep fence intact.
        return {'decision': 'DO_NOT_SEND', 'state': state, 'message': 'No authoritative effect receipt; reservation remains.'}
