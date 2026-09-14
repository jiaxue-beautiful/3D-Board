import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('digest', ROOT / 'scripts/digest.py')
digest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(digest)


def source_row():
    return {
        'id': '0123456789abcdef0123', 'lane': 'news',
        'publishedAt': '2026-09-14T00:00:00Z', 'url': 'https://example.com/news',
        'title': 'English title', 'author': 'Author', 'sourceId': 'example',
        'sourceName': 'Example source', 'category': 'AI 3D', 'dateEvidence': '2026-09-14',
        'sourceText': 'This is a source description long enough for evidence.',
    }


class ChineseDigestTests(unittest.TestCase):
    def test_fallback_is_readable_without_leaking_english_title(self):
        draft = digest.local_fallback(source_row())
        self.assertEqual(draft['title']['text'], '暂无中文标题')
        self.assertIn('暂无中文整理', draft['summary']['text'])

    def test_english_model_title_is_rejected(self):
        row = source_row()
        fact = {'text': 'English only', 'quote': row['sourceText']}
        draft = {'relevant': True, **{name: fact for name in digest.FACTS},
                 **{name: '中文分析' for name in digest.IDEAS}}
        with self.assertRaises(digest.EvidenceError):
            digest.validate(row, draft, '2026-09-14T01:00:00Z')


if __name__ == '__main__':
    unittest.main()
