"""Bounded cursor collector using existing read-only shared Slack equipment."""
import json
import re
import time

class SlackCollector:
    def __init__(self, coordinator, equipment):
        self.coordinator, self.equipment = coordinator, equipment

    def state(self, key):
        with self.coordinator.transaction() as db:
            row = db.execute('SELECT state FROM sources WHERE id=?', (key,)).fetchone()
            return json.loads(row['state']) if row else {}

    def save(self, key, value):
        with self.coordinator.transaction() as db:
            db.execute('INSERT INTO sources VALUES(?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state', (key, json.dumps(value)))

    def read(self, key, method, payload):
        state = self.state(key)
        if state.get('retry_after', 0) > time.time():
            return None
        try:
            result = self.equipment.slack(method, payload, fresh=True)
            if not result.get('ok'):
                self.save(key, {**state, 'error': result.get('error', 'read_failed'),
                               'retry_after': time.time() + int(result.get('retry_after') or 60), 'complete': False})
                return None
            return result
        except Exception as exc:
            self.save(key, {**state, 'error': type(exc).__name__, 'retry_after': time.time() + 60, 'complete': False})
            return None

    def observe(self, channel, message):
        oid = 'slack:' + channel + ':' + message['ts']
        text = message.get('text', '')
        # Evidence only: unstructured posts never infer release, owner authority or SENT.
        data = {'channel': channel, 'ts': message['ts'], 'thread_ts': message.get('thread_ts'),
                'user': message.get('user'), 'claim_candidate': bool(re.search(r'\b(taking|claimed|working on|take|claim)\b', text, re.I)),
                'text': text, 'reply_count': message.get('reply_count', 0)}
        with self.coordinator.transaction() as db:
            db.execute('INSERT INTO observations VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET observed=excluded.observed,data=excluded.data',
                       (oid, 'slack:' + channel, time.time(), json.dumps(data)))
        # Structured registrations are durable evidence from message with explicit scope.
        marker = re.search(r'<collision_claim>(.*?)</collision_claim>', text, re.S)
        if marker:
            try:
                claim = json.loads(marker.group(1))
                claim['operation_id'] = oid
                claim['owner'] = message.get('user', 'unknown')
                self.coordinator.take(claim)
            except (ValueError, KeyError, TypeError):
                pass
        elif data['claim_candidate']:
            # Narrow automatic extraction: exact repository/project URL plus a
            # current work assertion. Old provider claims remain evidence, not
            # renewed planning leases. Unknown project identity stays unresolved.
            matches = re.findall(r'https?://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:/(issues|pull)/(\d+))?', text)
            for repo, resource_kind, number in matches:
                age = max(0, time.time() - float(message['ts']))
                if age >= 1800:
                    continue
                inferred = {'operation_id': oid + ':' + repo, 'owner': message.get('user', 'unknown'),
                            'entity': 'github.com/' + repo, 'description': text,
                            'resources': [resource_kind + '/' + number] if number else [],
                            'ttl_seconds': max(30, int(1800 - age))}
                self.coordinator.take(inferred)

    def tick(self, max_requests=8):
        # One channel page per tick, retained cursor discovers future channels.
        catalog = self.state('slack:channels')
        result = self.read('slack:channels', 'conversations.list', {'limit': 100, 'cursor': catalog.get('cursor', ''), 'exclude_archived': 'true'})
        calls = 1
        if result:
            known = catalog.get('channels', [])
            known = sorted(set(known) | {c['id'] for c in result.get('channels', [])})
            self.save('slack:channels', {'channels': known, 'cursor': result.get('response_metadata', {}).get('next_cursor', ''),
                                       'complete': not result.get('response_metadata', {}).get('next_cursor'), 'index': catalog.get('index', 0)})
            catalog = self.state('slack:channels')
        channels = catalog.get('channels', [])
        if not channels:
            return {'requests': calls, 'channels': 0}
        index = catalog.get('index', 0)
        channel = channels[index % len(channels)]
        key = 'slack:' + channel
        state = self.state(key)
        # Continue pending history page from same watermark; advance only after final page.
        payload = {'channel': channel, 'limit': 100, 'oldest': state.get('oldest', str(time.time() - 86400)), 'inclusive': 'false', 'cursor': state.get('cursor', '')}
        history = self.read(key, 'conversations.history', payload)
        calls += 1
        if history:
            messages = history.get('messages', [])
            watermark = max([float(state.get('watermark', 0))] + [float(m['ts']) for m in messages])
            pending = state.get('threads', {})
            for message in messages:
                self.observe(channel, message)
                if message.get('reply_count'):
                    pending.setdefault(message['ts'], {'cursor': '', 'oldest': '0'})
            cursor = history.get('response_metadata', {}).get('next_cursor', '')
            state = {**state, 'cursor': cursor, 'watermark': str(watermark), 'oldest': payload['oldest'] if cursor else str(watermark), 'complete': not cursor, 'threads': pending, 'error': None}
            self.save(key, state)
        # Active threads remain scheduled even when parent message predates watermark.
        threads = list(state.get('threads', {}).items())
        thread_index = state.get('thread_index', 0)
        threads = threads[thread_index:] + threads[:thread_index]
        visited_threads = 0
        for root, thread in threads:
            if calls >= max_requests:
                break
            result = self.read(key + ':thread:' + root, 'conversations.replies', {'channel': channel, 'ts': root, 'oldest': thread['oldest'], 'cursor': thread['cursor'], 'limit': 100})
            calls += 1
            visited_threads += 1
            if result:
                messages = result.get('messages', [])
                for message in messages:
                    self.observe(channel, message)
                cursor = result.get('response_metadata', {}).get('next_cursor', '')
                thread['cursor'] = cursor
                if not cursor and messages:
                    thread['oldest'] = str(max(float(m['ts']) for m in messages))
                self.save(key, state)
        if threads:
            state['thread_index'] = (thread_index + visited_threads) % len(threads)
            self.save(key, state)
        catalog['index'] = index + 1
        self.save('slack:channels', catalog)
        return {'requests': calls, 'channels': len(channels), 'visited': channel}
