import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import briefs
import digest
from collect import atomic_json
from test_chinese_digest import source_row


class SourceBriefTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = '2026-09-14T01:00:00Z'
        self.row = source_row()
        self.row['id'] = hashlib.sha256(self.row['url'].encode()).hexdigest()[:20]
        atomic_json(self.root / 'config/sources.json', [{'id': 'example', 'lane': 'news', 'hosts': ['example.com']}])
        atomic_json(self.root / 'data/digest.json', {'version': 1, 'checkedAt': self.now, 'news': [], 'cases': []})
        self.inputs([self.row])

    def inputs(self, rows, now=None):
        now = now or self.now
        atomic_json(self.root / '.work/source-records.json', {'checkedAt': now, 'records': rows})
        atomic_json(self.root / 'data/report.json', {'checkedAt': now, 'checks': [{'id': 'example', 'ok': True, 'lane': 'news'}]})

    def test_budget_block_does_not_hide_fresh_source(self):
        briefs.update(self.root)
        def blocked(row):
            raise digest.BudgetError('uncertain ledger')
        result = digest.update(self.root, self.now, blocked)
        self.assertEqual(len(result['sourceNews']), 1)
        self.assertEqual(result['news'], [])
        self.assertEqual(result['pending'][0]['status'], 'budget_blocked')
        self.assertNotIn('sourceText', result['sourceNews'][0])
        self.assertEqual(result['sourceNews'][0]['excerpt'], self.row['sourceText'])

    def test_cross_day_retains_first_seen_and_no_duplicates(self):
        first = briefs.update(self.root)['sourceNews'][0]
        self.inputs([self.row, self.row], '2026-09-15T01:00:00Z')
        result = briefs.update(self.root)
        self.assertEqual(len(result['sourceNews']), 1)
        self.assertEqual(result['sourceProcessing']['newCount'], 0)
        self.assertEqual(result['sourceNews'][0]['firstSeenAt'], first['firstSeenAt'])
        self.assertEqual(result['sourceNews'][0]['publishedAt'], self.row['publishedAt'])

    def test_new_seven_day_item_is_caught_up_but_older_not_added(self):
        self.inputs([self.row], '2026-09-20T01:00:00Z')
        self.assertEqual(briefs.update(self.root)['sourceProcessing']['newCount'], 1)
        other = self.row | {'url': 'https://example.com/older', 'publishedAt': '2026-09-01T00:00:00Z'}
        other['id'] = hashlib.sha256(other['url'].encode()).hexdigest()[:20]
        self.inputs([other], '2026-09-21T01:00:00Z')
        result = briefs.update(self.root)
        self.assertEqual(len(result['sourceNews']), 1)
        self.assertEqual(result['sourceProcessing']['newCount'], 0)

    def test_future_unknown_host_and_bad_identity_are_rejected(self):
        self.inputs([self.row | {'publishedAt': '2099-01-01T00:00:00Z'},
                     self.row | {'url': 'https://other.example/news'},
                     self.row | {'id': 'a' * 20}])
        result = briefs.update(self.root)
        self.assertEqual(result['sourceNews'], [])
        self.assertEqual(result['sourceProcessing']['invalidCount'], 3)

    def test_failure_and_cutoff_mismatch_preserve_previous_file(self):
        path = self.root / 'data/digest.json'
        before = path.read_bytes()
        atomic_json(self.root / 'data/report.json', {'checkedAt': self.now, 'checks': []})
        with self.assertRaises(ValueError):
            briefs.update(self.root)
        self.assertEqual(path.read_bytes(), before)

    def test_editor_translation_is_bound_to_exact_source(self):
        atomic_json(self.root / 'config/editorial-notes.json', {self.row['id']: {
            'sourceDigest': digest.fingerprint(self.row), 'titleZh': '中文标题', 'summaryZh': '中文概述'}})
        self.assertEqual(briefs.update(self.root)['sourceNews'][0]['contentStatus'], 'editor_summary')
        self.inputs([self.row | {'sourceText': self.row['sourceText'] + ' changed'}])
        changed = briefs.update(self.root)['sourceNews'][0]
        self.assertNotIn('titleZh', changed)
        self.assertEqual(changed['contentStatus'], 'source_only')


if __name__ == '__main__':
    unittest.main()
