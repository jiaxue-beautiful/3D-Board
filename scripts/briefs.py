"""Publish attributed source metadata independently of paid AI enrichment."""
import argparse
from datetime import timedelta
import hashlib
import json
from pathlib import Path

from collect import atomic_json, instant, safe_url
from digest import source_check, EvidenceError, fingerprint


def update(root):
    root = Path(root)
    original = json.loads((root / '.work/source-records.json').read_text())
    report = json.loads((root / 'data/report.json').read_text())
    now = original['checkedAt']
    end = instant(now)
    if end is None or report.get('checkedAt') != now:
        raise ValueError('Source cutoff mismatch')
    sources = {s['id']: s for s in json.loads((root / 'config/sources.json').read_text())}
    successful = {c['id'] for c in report['checks'] if c.get('ok') and c['lane'] == 'news'}
    if not successful:
        raise ValueError('No successful news source; preserve prior publication')
    path = root / 'data/digest.json'
    previous = json.loads(path.read_text())
    if previous.get('version') != 1 or (instant(previous.get('checkedAt')) or end) > end:
        raise ValueError('Invalid or newer published state; do not overwrite')
    archive = {r['url']: r for r in previous.get('sourceNews', [])}
    notes_path = root / 'config/editorial-notes.json'
    notes = json.loads(notes_path.read_text()) if notes_path.exists() else {}
    added, invalid = [], 0
    for row in original['records']:
        if row.get('lane') != 'news':
            continue
        source = sources.get(row.get('sourceId'))
        try:
            source_check(row, now)
            if (not source or source['lane'] != 'news' or row['sourceId'] not in successful
                    or safe_url(row['url'], source['hosts']) != row['url']
                    or hashlib.sha256(row['url'].encode()).hexdigest()[:20] != row['id']):
                raise EvidenceError('Source identity mismatch')
        except EvidenceError:
            invalid += 1
            continue
        # Seven-day catch-up avoids losing entries during temporary outages.
        # Original publication dates never change and old items are not "today".
        if row['url'] not in archive and instant(row['publishedAt']) <= end - timedelta(days=7):
            continue
        old = archive.get(row['url'])
        if old is None:
            added.append(row['id'])
        item = {key: row[key] for key in ('id', 'url', 'title', 'publishedAt', 'sourceId',
                                         'sourceName', 'lane', 'category', 'author', 'dateEvidence')}
        item.update(excerpt=row['sourceText'][:280], firstSeenAt=old['firstSeenAt'] if old else now,
                    checkedAt=now, sourceDigest=fingerprint(row), contentStatus='source_only')
        note = notes.get(row['id'], {})
        if (note.get('sourceDigest') == item['sourceDigest']
                and isinstance(note.get('titleZh'), str) and isinstance(note.get('summaryZh'), str)):
            item.update(titleZh=note['titleZh'], summaryZh=note['summaryZh'], contentStatus='editor_summary')
        archive[row['url']] = item
    previous.update(checkedAt=now, checks=report['checks'],
                    sourceNews=sorted(archive.values(), key=lambda r: r['publishedAt'], reverse=True),
                    sourceProcessing={'checkedAt': now, 'status': 'updated', 'newCount': len(added),
                                      'newIds': added, 'invalidCount': invalid,
                                      'successfulSources': len(successful)})
    atomic_json(path, previous)
    return previous


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    result = update(args.root)
    print(json.dumps(result['sourceProcessing']))
