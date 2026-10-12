import concurrent.futures
import tempfile
import unittest
from pathlib import Path
from coordinator import Coordinator, digest

class FocusedChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.clock = [1000]
        self.db = Coordinator(Path(self.temp.name) / 'state.db', lambda: self.clock[0])
    def tearDown(self): self.temp.cleanup()
    def work(self, oid, description, **extra):
        return {'operation_id': oid, 'owner': oid, 'entity': 'https://github.com/lab/app', 'description': description, **extra}
    def send(self, oid, actor='lab', **extra):
        return {'operation_id': oid, 'provider': 'gmail', 'conversation_id': 'thread-123', 'action': 'reply',
                'payload_hash': digest('approved reply'), 'source_version': 'v1', 'actor': actor, **extra}
    def test_semantic_overlap_and_compatible_angle(self):
        self.assertEqual(self.db.take(self.work('a', 'repair OAuth login'))['decision'], 'TAKEN')
        self.assertEqual(self.db.take(self.work('b', 'fix authentication sign in'))['decision'], 'CHOOSE_DIFFERENT_ANGLE')
        self.assertEqual(self.db.take(self.work('c', 'improve billing checkout'))['decision'], 'TAKEN')
        self.assertEqual(self.db.take(self.work('d', 'read login code', kind='read'))['decision'], 'TAKEN')
    def test_stale_work_releases_but_unknown_send_does_not(self):
        self.db.take(self.work('a', 'login'))
        self.clock[0] += 400
        self.assertEqual(self.db.take(self.work('b', 'authentication'))['decision'], 'TAKEN')
        def fail(_): raise TimeoutError()
        with self.assertRaises(TimeoutError): self.db.dispatch(self.send('s1'), fail, lambda *_: None)
        self.clock[0] += 999999
        self.assertEqual(self.db.reserve(self.send('s2'))['decision'], 'DO_NOT_SEND')
    def test_simultaneous_dispatch_has_one_provider_call(self):
        calls = []
        def run(n):
            return self.db.dispatch(self.send('s' + str(n), actor='actor' + str(n)),
                lambda request: calls.append(request['operation_id']) or {'id': 'receipt'},
                lambda effect, request: {'verified': True, 'actor': request['actor'], 'provider_id': effect['id']})
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
            results = list(executor.map(run, range(12)))
        self.assertEqual(len(calls), 1)
        self.assertEqual(sum(r['decision'] == 'SENT' for r in results), 1)
    def test_changed_binding_and_restart_do_not_reauthorize(self):
        self.db.reserve(self.send('s1'))
        with self.assertRaises(ValueError):
            self.db.transition('s1', 'RESERVED', 'DISPATCHED', binding={})
        reopened = Coordinator(self.db.path)
        self.assertEqual(reopened.reserve(self.send('s1'))['send_authorized'], False)
        self.assertEqual(reopened.reserve(self.send('s2', payload_hash=digest('reworded')))['decision'], 'DO_NOT_SEND')
    def test_ambiguous_project_does_not_silently_clear(self):
        self.db.take(self.work('a', 'work on project'))
        self.assertEqual(self.db.take(self.work('b', 'implement changes'))['decision'], 'TAKEN_WITH_SCOPE_ADVICE')

if __name__ == '__main__': unittest.main()
