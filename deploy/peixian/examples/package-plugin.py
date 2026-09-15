"""Package reviewed local modules without downloading or executing dependencies."""
import argparse
import json
from pathlib import Path
import re
import zipfile

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, default=root.parent / 'dist/plugins/sample-records-1.0.0.zip')
parser.add_argument('--version', default='1.0.0')
args = parser.parse_args()
if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', args.version):
    raise SystemExit('invalid_version')
manifest = json.loads((root / 'records-plugin/manifest.json').read_text(encoding='utf-8'))
manifest['version'] = args.version
source = (root / 'records-plugin/entry.mjs').read_text(encoding='utf-8').replace('const VERSION = "1.0.0";', 'const VERSION = ' + json.dumps(args.version) + ';')
args.output.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(args.output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
    archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False))
    archive.writestr('entry.mjs', source)
print('Packaged sample-records ' + args.version)
