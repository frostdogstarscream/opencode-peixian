"""Minimal release-owned draft/published/disabled method catalog, without new tables."""
import hashlib,json
from pathlib import Path
DATA=json.loads(Path(__file__).with_name('official_methods.json').read_text())
BY_HASH={value['sha256']:value for value in DATA['skills']}
BY_ID={value['id']:value for value in DATA['skills']}
if any(v['state'] not in ('draft','published','disabled') or hashlib.sha256(v['content'].encode()).hexdigest()!=v['sha256'] for v in BY_ID.values()):
    raise RuntimeError('official_method_manifest_invalid')
def identify(content):return BY_HASH.get(hashlib.sha256(content.encode()).hexdigest())
def public(value):return {k:value[k] for k in ('id','version','state','method','dependency_ids','sha256')}
