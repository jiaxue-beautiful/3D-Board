"""Publish only explicitly allowed files and public data."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import urlsplit

ASSETS = ['app.js', 'case-ui.js', 'data-ui.js', 'report-utils.js', 'styles.css', '_headers']
OUTPUTS = set(ASSETS + ['index.html', 'site-data.js', 'report.json'])
CASE_FIELDS = ('id title author platform format use desc combination tools method evidence unknown hook videoIdea postIdea adaptation nature url originalTitle originalPublishedAt publishedLabel collectedAt checkedAt checkLabel chapters').split()


def valid_url(value):
    try:
        u = urlsplit(value)
        return u.scheme == 'https' and bool(u.hostname) and not u.username and not u.password
    except (ValueError, TypeError):
        return False


def validate_report(report):
    if report.get('schemaVersion') != 1:
        raise ValueError('Unsupported report schema')
    for key in ('events', 'archive', 'caseCandidates'):
        if not isinstance(report.get(key), list):
            raise ValueError('Invalid report list: ' + key)
        ids = set()
        for row in report[key]:
            if not isinstance(row, dict) or not re.fullmatch('[a-zA-Z0-9_-]{1,100}', row.get('id', '')):
                raise ValueError('Invalid item ID')
            if row['id'] in ids or not valid_url(row.get('url')) or not isinstance(row.get('title'), str):
                raise ValueError('Invalid source item')
            ids.add(row['id'])
            if row.get('publishedAt'):
                if datetime.fromisoformat(row['publishedAt'].replace('Z', '+00:00')).tzinfo is None:
                    raise ValueError('Timezone missing')
            if key != 'caseCandidates':
                if not row.get('sources') or any(not valid_url(s[1]) for s in row['sources']):
                    raise ValueError('Invalid source link')
                for name in ('summary', 'background', 'signal', 'category', 'status', 'type'):
                    if not isinstance(row.get(name), str):
                        raise ValueError('Missing display field: ' + name)
                if not isinstance(row.get('tags'), list):
                    raise ValueError('Missing tags')
    return report


def build(root, destination):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    if destination == root or root.is_relative_to(destination):
        raise ValueError('Unsafe destination')
    if destination.exists() and any(p.name not in OUTPUTS or p.is_symlink() or p.is_dir() for p in destination.iterdir()):
        raise ValueError('Destination contains non-build files; refusing to overwrite or publish')
    report = validate_report(json.loads((root / 'data/report.json').read_text()))
    curated = json.loads(subprocess.check_output(['node', '-e', 'process.stdout.write(JSON.stringify(require(process.argv[1])))', str(root / 'social-cases.js')], text=True))
    cases = []
    for case in curated:
        if not valid_url(case.get('url')):
            raise ValueError('Invalid case link')
        public = {k: case[k] for k in CASE_FIELDS if k in case}
        public['image'] = None
        cases.append(public)
    public_report = {k: report[k] for k in ('schemaVersion', 'checkedAt', 'windowStart', 'windowEnd', 'mode', 'checks', 'events', 'archive', 'caseCandidates', 'notice')}
    html = (root / 'index.html').read_text()
    html = re.sub(r'<script src="social-cases.js[^\"]*" defer></script>', '<script src="site-data.js" defer></script>', html)
    destination.mkdir(parents=True, exist_ok=True)
    for name in ASSETS:
        shutil.copyfile(root / name, destination / name)
    (destination / 'index.html').write_text(html)
    (destination / 'report.json').write_text(json.dumps(public_report, ensure_ascii=False))
    payload = json.dumps({'publicMode': True, 'report': public_report, 'cases': cases}, ensure_ascii=False)
    (destination / 'site-data.js').write_text('globalThis.RADAR_DATA = ' + payload + ';\n')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    print(build(args.root, args.out or args.root / 'dist'))
