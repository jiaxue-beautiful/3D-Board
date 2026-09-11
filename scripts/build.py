import argparse, hashlib, json
from pathlib import Path
import shutil

ASSETS=('index.html','app.js','styles.css','social-cases.js','case-ui.js','data-ui.js','_headers')

def build(root,destination):
 root,destination=Path(root).resolve(),Path(destination).resolve()
 if destination==root or root.is_relative_to(destination): raise ValueError('Unsafe destination')
 if destination.exists() and any(destination.iterdir()): raise ValueError('Output must be empty')
 manifest=json.loads((root/'frozen-manifest.json').read_text())
 for row in manifest['files']:
  if row['path'].startswith('media/social/'):
   p=root/row['path']
   if not p.is_file() or p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=row['sha256']: raise ValueError('Approved media changed')
 digest=root/'data/digest.json'; report=json.loads(digest.read_text())
 if report.get('version')!=1 or not isinstance(report.get('news'),list) or not isinstance(report.get('cases'),list): raise ValueError('Invalid digest')
 names=[*ASSETS,*[r['path'] for r in manifest['files'] if r['path'].startswith('media/social/')],'data/digest.json']
 for name in names:
  p=root/name
  if not p.is_file() or p.is_symlink(): raise ValueError('Missing public asset')
 destination.mkdir(parents=True,exist_ok=True)
 for name in names:
  p=destination/name; p.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(root/name,p)
 return destination

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--out',type=Path);a=p.parse_args();print(build(a.root,a.out or a.root/'dist'))
