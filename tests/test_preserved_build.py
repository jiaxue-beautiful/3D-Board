import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('site_builder', ROOT / 'scripts/build.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

class PreservedBuildTests(unittest.TestCase):
    def test_preserves_templates_images_and_actual_data_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source'
            source.mkdir()
            for name in ('index.html','app.js','styles.css','social-cases.js','case-ui.js','data-ui.js','_headers'):
                (source / name).write_bytes((ROOT / name).read_bytes())
            (source / 'media/social').mkdir(parents=True)
            for row in json.loads((ROOT / 'frozen-manifest.json').read_text())['files']:
                if row['path'].startswith('media/'):
                    (source / row['path']).write_bytes((ROOT / row['path']).read_bytes())
            (source / 'frozen-manifest.json').write_bytes((ROOT / 'frozen-manifest.json').read_bytes())
            (source / 'data').mkdir()
            (source / 'data/digest.json').write_text('{"version":1,"news":[],"cases":[]}')
            (source / '.env').write_text('PRIVATE_SECRET')
            output = Path(tmp) / 'site'
            builder.build(source, output)
            for name in ('index.html','styles.css','social-cases.js','case-ui.js'):
                self.assertEqual((output / name).read_bytes(), (source / name).read_bytes())
            self.assertEqual(len(list((output / 'media/social').iterdir())),10)
            self.assertTrue((output / 'data/digest.json').exists())
            self.assertFalse((output / 'site-data.js').exists())
            self.assertFalse((output / '.env').exists())

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'site'
            output.mkdir()
            (output / 'private.txt').write_text('preserve')
            with self.assertRaises(ValueError):
                builder.build(ROOT, output)
            self.assertEqual((output / 'private.txt').read_text(),'preserve')
