import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import digest
import publish_data
from test_chinese_digest import source_row


def draft(row):
    return {'relevant': True,
            **{name: {'text': '来源中的三维内容说明', 'quote': row['sourceText']} for name in digest.FACTS},
            **{name: '建议进一步测试' for name in digest.IDEAS}}


class DailyContinuityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = '2026-09-14T01:00:00Z'
        self.rows = [source_row() | {'id': f'{i:020x}', 'url': f'https://example.com/{i}'} for i in range(4)]
        self.inputs(self.now, self.rows)

    def inputs(self, now, rows):
        digest.atomic_json(self.root / '.work/source-records.json', {'checkedAt': now, 'records': rows})
        digest.atomic_json(self.root / 'data/report.json', {'checkedAt': now, 'checks': [{'ok': True, 'lane': 'news'}]})

    def test_two_calls_then_cross_day_queue_and_archive(self):
        calls = []
        def generate(row):
            calls.append(row['id'])
            return draft(row)
        first = digest.update(self.root, self.now, generate)
        self.assertEqual((len(calls), len(first['news']), len(first['pending'])), (2, 2, 2))
        later = '2026-09-16T01:00:00Z'
        self.inputs(later, self.rows)
        second = digest.update(self.root, later, generate)
        self.assertEqual((len(calls), len(second['news']), len(second['pending'])), (4, 4, 0))
        self.assertEqual(second['todayIds'], [])

    def test_failure_is_pending_not_accepted_and_next_item_runs(self):
        def generate(row):
            if row['id'] == self.rows[0]['id']:
                raise RuntimeError('gateway unavailable')
            return draft(row)
        result = digest.update(self.root, self.now, generate)
        self.assertEqual(len(result['news']), 1)
        self.assertEqual(result['pending'][0]['status'], 'generation_failed')
        self.assertEqual(result['processing']['status'], 'partial')
        self.assertNotIn('sourceText', json.dumps(result['pending']))

    def test_placeholders_rejected_and_old_placeholder_retried(self):
        row = self.rows[0]
        with self.assertRaises(digest.EvidenceError):
            digest.validate(row, digest.local_fallback(row), self.now)
        good = digest.validate(row, draft(row), self.now)
        digest.atomic_json(self.root / 'data/digest.json', {'version': 1, 'news': [good | {'title': digest.NO_CHINESE_TITLE}], 'cases': []})
        self.inputs(self.now, [row])
        result = digest.update(self.root, self.now, draft)
        self.assertEqual(result['news'][0]['title'], '来源中的三维内容说明')
        self.assertEqual(result['outcomes'][0]['status'], 'accepted')

    def test_invalid_draft_preserves_good_previous_content(self):
        row = self.rows[0]
        good = digest.validate(row, draft(row), self.now)
        digest.atomic_json(self.root / 'data/digest.json', {'version': 1, 'news': [good], 'cases': []})
        self.inputs(self.now, [row | {'sourceText': row['sourceText'] + ' Changed.'}])
        result = digest.update(self.root, self.now, lambda r: {})
        self.assertEqual(result['news'], [good])
        self.assertEqual(result['pending'][0]['status'], 'invalid_draft')

    def test_budget_block_stops_attempts(self):
        calls = []
        def generate(row):
            calls.append(row)
            raise digest.BudgetError('blocked')
        result = digest.update(self.root, self.now, generate)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(result['pending']), 4)
        self.assertEqual(result['news'], [])

    def test_irrelevant_is_remembered_without_repeat_charge(self):
        self.inputs(self.now, [self.rows[0]])
        first = digest.update(self.root, self.now, lambda r: {'relevant': False})
        self.assertEqual(first['outcomes'][0]['status'], 'not_relevant')
        second = digest.update(self.root, self.now, lambda r: self.fail('must not call twice'))
        self.assertEqual(second['processing']['attempted'], 0)

    def test_daily_limit_is_deferral_not_generation_success_or_failure(self):
        def generate(row):
            raise digest.DailyLimitError('daily calls used')
        result = digest.update(self.root, self.now, generate)
        self.assertTrue(all(r['status'] == 'pending_budget' for r in result['pending']))
        self.assertEqual(result['news'], [])

    def test_missing_source_stays_pending_without_fabricated_evidence(self):
        digest.update(self.root, self.now, draft)
        self.inputs('2026-09-16T01:00:00Z', [])
        result = digest.update(self.root, '2026-09-16T01:00:00Z', draft)
        self.assertEqual(len(result['news']), 2)
        self.assertEqual(len(result['pending']), 2)
        self.assertTrue(all(r['status'] == 'awaiting_source' for r in result['pending']))

    def test_restore_requires_valid_remote_data_before_overwrite(self):
        path = self.root / 'data/digest.json'
        previous = {'version': 1, 'checkedAt': self.now, 'news': [], 'cases': [], 'pending': []}
        digest.atomic_json(path, previous)
        remote = previous | {'checkedAt': '2026-09-15T01:00:00Z'}
        def response(data):
            return {'content': base64.b64encode(json.dumps(data).encode()).decode()}
        with patch.dict('os.environ', {'GITHUB_TOKEN': 'test', 'GITHUB_REPOSITORY': 'test/repo'}):
            with patch.object(publish_data, 'api_request', return_value=response(remote)):
                publish_data.restore(self.root)
            self.assertEqual(json.loads(path.read_text()), remote)
            with patch.object(publish_data, 'api_request', return_value=response({})):
                with self.assertRaises(ValueError):
                    publish_data.restore(self.root)
            self.assertEqual(json.loads(path.read_text()), remote)


if __name__ == '__main__':
    unittest.main()
