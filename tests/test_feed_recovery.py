import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from collect import parse_feed, CollectionError, download


class FeedRecoveryTests(unittest.TestCase):
    source = dict(id='blender-dev', name='Blender', hosts=['code.blender.org'], lane='news', category='传统建模')

    def test_html_doctype_inside_cdata_is_plain_content(self):
        feed = '''<rss><channel><item><title>Article</title><link>https://code.blender.org/article/</link>
        <pubDate>Thu, 17 Sep 2026 12:00:00 +0000</pubDate>
        <description><![CDATA[<!DOCTYPE html><html><body>Real article text</body></html>]]></description>
        </item></channel></rss>'''
        rows = parse_feed(feed, self.source, include_text=True)
        self.assertEqual(rows[0]['sourceText'], 'Real article text')
        self.assertEqual(rows[0]['publishedAt'], '2026-09-17T12:00:00Z')

    def test_actual_xml_doctype_is_still_rejected(self):
        with self.assertRaises(CollectionError):
            parse_feed('<!DOCTYPE rss [<!ENTITY x "value">]><rss/>', self.source)

    def test_transient_http_error_has_bounded_retries(self):
        error = HTTPError('https://arxiv.org/', 503, 'Unavailable', {}, None)
        with patch('collect.urlopen', side_effect=error) as request, patch('collect.time.sleep') as sleep:
            with self.assertRaises(HTTPError):
                download('https://arxiv.org/')
            self.assertEqual(request.call_count, 3)
            self.assertEqual(sleep.call_count, 2)

    def test_access_denied_is_not_retried(self):
        error = HTTPError('https://arxiv.org/', 403, 'Forbidden', {}, None)
        with patch('collect.urlopen', side_effect=error) as request, patch('collect.time.sleep') as sleep:
            with self.assertRaises(HTTPError):
                download('https://arxiv.org/')
            self.assertEqual(request.call_count, 1)
            sleep.assert_not_called()
