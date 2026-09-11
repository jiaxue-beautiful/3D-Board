"""Independent radar ingestion. No dependency on the AI Coding pipeline."""
import argparse
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
from html import unescape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


class CollectionError(Exception):
    pass


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, value):
        self.parts.append(value)


def plain(value):
    parser = PlainText()
    parser.feed(value or '')
    return ' '.join(unescape(' '.join(parser.parts)).split())


def instant(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        try:
            result = parsedate_to_datetime(value)
        except (ValueError, TypeError):
            return None
    return result.astimezone(timezone.utc) if result.tzinfo else None


def stamp(value):
    return value.isoformat().replace('+00:00', 'Z')


def safe_url(url, hosts=None):
    try:
        u = urlsplit(url)
        host = u.hostname or ''
        if u.scheme != 'https' or not host or u.username or u.password or u.port not in (None, 443):
            return None
        if hosts and not any(host == h or host.endswith('.' + h) for h in hosts):
            return None
        query = [(k, v) for k, v in parse_qsl(u.query) if not k.startswith('utm_') and k not in ('fbclid', 'gclid')]
        return urlunsplit(('https', host, u.path, urlencode(query), ''))
    except (ValueError, TypeError):
        return None


def record(source, title, url, published, text, author='', include_text=False):
    url = safe_url(url, source['hosts'])
    if not url or not plain(title):
        return None
    published = instant(published)
    row = {'id': hashlib.sha256(url.encode()).hexdigest()[:20], 'url': url,
            'title': plain(title)[:240], 'excerpt': plain(text)[:280],
            'publishedAt': stamp(published) if published else None,
            'sourceId': source['id'], 'sourceName': source['name'],
            'lane': source['lane'], 'category': source['category'],
            'author': plain(author) or source['name'], 'dateEvidence': '原始订阅条目的发布时间字段'}
    if include_text:
        row['sourceText'] = plain(text)[:12000]
    return row


def parse_feed(text, source, include_text=False):
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        raise CollectionError('XML declarations not accepted')
    root = ET.fromstring(text)
    local = lambda e: e.tag.rsplit('}', 1)[-1]
    if local(root) not in ('feed', 'rss', 'RDF'):
        raise CollectionError('Not a feed')
    result = []
    for entry in root.iter():
        if local(entry) not in ('entry', 'item'):
            continue
        children = {local(e): e for e in entry}
        def field(*names):
            for name in names:
                if name in children:
                    return ''.join(children[name].itertext()).strip()
            return ''
        links = [e for e in entry if local(e) == 'link' and e.get('rel', 'alternate') == 'alternate']
        url = (links[0].get('href') or links[0].text or '') if links else ''
        if url.startswith('http://arxiv.org/'):
            url = 'https://' + url[7:]
        description = field('encoded', 'content', 'description', 'summary')
        if not description:
            description = next((''.join(e.itertext()) for e in entry.iter()
                                if local(e) == 'description'), '')
        author = field('author', 'creator')
        if 'author' in children:
            author = next((''.join(e.itertext()) for e in children['author']
                           if local(e) == 'name'), author)
        row = record(source, field('title'), url, field('published', 'pubDate'),
                     description, author, include_text=include_text)
        if row:
            result.append(row)
    return result


def parse_releases(text, source, include_text=False):
    items = json.loads(text)
    if not isinstance(items, list):
        raise CollectionError('Not a release list')
    return [row for item in items if not item.get('draft') and not item.get('prerelease')
            if (row := record(source, item.get('name') or item.get('tag_name', ''),
                              item.get('html_url', ''), item.get('published_at'), item.get('body', ''),
                              include_text=include_text))]


def as_event(row):
    return {**row, 'date': row['publishedAt'], 'status': '来源更新', 'type': '原始来源动态',
            'summary': row['excerpt'] or '来源未提供摘要，请打开原文。',
            'background': '当前仅采集来源标题、发布时间与订阅摘要，尚未完成全文核对和中文分析。',
            'signal': '按原始发布时间排序；没有持续互动采样，不判断爆款或升温。',
            'evidence': [['来源摘要 · 非全文核验', row['excerpt'] or '来源没有摘要']],
            'sources': [[row['sourceName'], row['url']]], 'tags': [row['category']]}


def merge_report(previous, rows, checks, now):
    end = instant(now)
    if end is None:
        raise CollectionError('Invalid cutoff')
    if not any(c['ok'] and c['lane'] == 'news' for c in checks):
        raise CollectionError('All news sources failed; previous report retained')
    start = end - timedelta(hours=24)
    archive = {r['url']: r for r in previous.get('archive', [])}
    cases = {r['url']: r for r in previous.get('caseCandidates', [])}
    for row in rows:
        pub = instant(row['publishedAt'])
        if pub and pub > end:
            continue
        target = cases if row['lane'] == 'cases' else archive
        first = target.get(row['url'], {}).get('firstSeenAt', now)
        target[row['url']] = {**(row if row['lane'] == 'cases' else as_event(row)), 'firstSeenAt': first}
    ordered = sorted(archive.values(), key=lambda r: r.get('publishedAt') or '', reverse=True)
    current = [r for r in ordered if (p := instant(r.get('publishedAt'))) and start <= p <= end]
    return {'schemaVersion': 1, 'checkedAt': now, 'windowStart': stamp(start), 'windowEnd': now,
            'mode': 'source_metadata', 'checks': checks, 'events': current, 'archive': ordered,
            'caseCandidates': sorted(cases.values(), key=lambda r: r.get('publishedAt') or '', reverse=True),
            'notice': '来源订阅采集；未启用 LLM 整理，不代表完整行业覆盖或爆款排名。'}


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.pending-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            out.write(text)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def download(url):
    if not safe_url(url):
        raise CollectionError('Invalid source URL')
    req = Request(url, headers={'User-Agent': '3D-Radar/1.0 (public feed reader)', 'Accept': 'application/atom+xml, application/rss+xml, application/json, text/xml'})
    with urlopen(req, timeout=25) as response:
        data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise CollectionError('Source too large')
        return data.decode('utf-8')


def update(root, now, transport=download, replay=False):
    root = Path(root)
    sources = json.loads((root / 'config/sources.json').read_text())
    path = root / 'data/report.json'
    previous = json.loads(path.read_text()) if path.exists() else {}
    rows, checks = [], []
    for source in sources:
        check = {'id': source['id'], 'name': source['name'], 'lane': source['lane'], 'ok': False, 'count': 0}
        cache = root / '.work/cache' / (source['id'] + '.json')
        try:
            if replay:
                cached = json.loads(cache.read_text())
                if cached['url'] != source['url'] or cached['checkedAt'] != now:
                    raise CollectionError('Replay source or cutoff mismatch')
                text = cached['payload']
            else:
                text = transport(source['url'])
                atomic_json(cache, {'url': source['url'], 'checkedAt': now, 'payload': text})
            parser = parse_releases if source['kind'] == 'github' else parse_feed
            batch = parser(text, source, include_text=True)
            rows.extend(batch)
            check.update(ok=True, count=len(batch))
        except Exception:
            check['error'] = '来源不可用或内容格式不符；未绕过访问限制'
        checks.append(check)
        if transport is download and not replay:
            time.sleep(1)
    atomic_json(root / '.work/status.json', {'checkedAt': now, 'checks': checks})
    public_rows = [{k: v for k, v in row.items() if k != 'sourceText'} for row in rows]
    report = merge_report(previous, public_rows, checks, now)
    atomic_json(root / '.work/source-records.json', {'checkedAt': now, 'records': rows})
    key = instant(now).strftime('%Y%m%dT%H%M%SZ')
    atomic_json(root / 'data/history' / (key + '.json'), report)
    atomic_json(path, report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--now', default=stamp(datetime.now(timezone.utc)))
    parser.add_argument('--replay', action='store_true')
    args = parser.parse_args()
    try:
        result = update(args.root, args.now, replay=args.replay)
        print(json.dumps({'checkedAt': result['checkedAt'], 'events': len(result['events']),
                          'caseCandidates': len(result['caseCandidates']), 'checks': result['checks']}, ensure_ascii=False))
    except CollectionError as error:
        raise SystemExit(str(error))
