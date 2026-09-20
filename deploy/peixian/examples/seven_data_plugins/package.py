"""Build reproducible plugin archives; never install or publish implicitly."""
import argparse, hashlib, json, zipfile
from pathlib import Path
MODULES=('funds','calls','portrait','composite','night','vehicle','lookup')
def build(destination):
    root=Path(__file__).parent
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    result=[]
    for module in MODULES:
        manifest=json.loads((root/module/'manifest.json').read_text())
        target=destination/(manifest['id']+'-'+manifest['version']+'.zip')
        with target.open('xb') as output:
            with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                for name in ('manifest.json','entry.mjs'):
                    info=zipfile.ZipInfo(name,date_time=(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
                    archive.writestr(info,(root/module/name).read_bytes())
        result.append({'id':manifest['id'],'version':manifest['version'],'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    return result
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('destination');args=parser.parse_args()
    print(json.dumps(build(args.destination),indent=2))
