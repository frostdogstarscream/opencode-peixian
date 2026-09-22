"""Render reviewed A/B overlays. This command never starts or stops containers."""
import argparse,hashlib,importlib.util,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def require(ok,code):
    if not ok:raise ValueError(code)

def projection(manifest,phase,accounts):
    require(phase in ('legacy','a','ab'),'invalid_rollout_phase')
    require(set(accounts)=={'alignment-a','alignment-b'} and all(isinstance(v,str) and re.fullmatch('[0-9a-f]{32}',v) for v in accounts.values()) and len(set(accounts.values()))==2,'invalid_test_account_map')
    require(manifest.get('schema_version')==9 and manifest.get('source_matches_commit') is True and manifest.get('contains_runtime_data') is False and manifest.get('data_environment')=='synthetic','invalid_candidate_manifest')
    revision=manifest.get('source_revision','');require(re.fullmatch('[0-9a-f]{40}',revision) is not None,'invalid_source_revision')
    images=manifest.get('images',{});require(set(images)=={'control','gateway','agent'},'incomplete_image_set')
    require(all(x.get('source_revision')==revision and re.fullmatch('sha256:[0-9a-f]{64}',x.get('image_id','')) for x in images.values()),'unmatched_image_set')
    ids=[] if phase=='legacy' else [accounts['alignment-a']] if phase=='a' else [accounts['alignment-a'],accounts['alignment-b']]
    env={'PX_TASKSPEC_V1_UIDS':','.join(ids),'PX_MULTI_AGENT_V1_UIDS':','.join(ids),'PX_TRUSTED_RESULT_V2_UIDS':','.join(ids)}
    # Offline migrations are separate; permanent runtime config never authorizes them.
    return {'images':{k:v['image_id'] for k,v in images.items()},'environment':env,'source_revision':revision,'phase':phase}

def prepare(config_path,package,expected_digest,accounts_path,phase,output):
    package=Path(package);manifest=package/'release-manifest.json'
    require(re.fullmatch('[0-9a-f]{64}',expected_digest) is not None and hashlib.sha256(manifest.read_bytes()).hexdigest()==expected_digest,'untrusted_manifest')
    # Full file/SBOM/plugin validation, not only a JSON claim.
    spec=importlib.util.spec_from_file_location('stage2_artifact',ROOT/'stage2-artifact.py');artifact=importlib.util.module_from_spec(spec);spec.loader.exec_module(artifact)
    artifact.validate_manifest(package,expected_digest)
    data=json.loads(Path(config_path).read_text());view=projection(json.loads(manifest.read_text()),phase,json.loads(Path(accounts_path).read_text()))
    output=Path(output).absolute();require(not output.exists() and not output.is_symlink(),'new_rollout_directory_required')
    output.mkdir(parents=True,mode=0o700);data['images'].update(view['images'])
    target=output/'platform.json';target.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    spec=importlib.util.spec_from_file_location('stage2_platform',ROOT/'platform-manage.py');platform=importlib.util.module_from_spec(spec);spec.loader.exec_module(platform)
    cfg=platform.config.load_config(target);pinned=platform.inspect_images(cfg);compose=platform.compose_config(cfg,pinned)
    compose['services']['console']['environment'].update(view['environment'])
    (output/'compose.json').write_text(json.dumps(compose,ensure_ascii=False,indent=2)+'\n')
    receipt={'status':'prepared','phase':phase,'source_revision':view['source_revision'],'manifest_sha256':expected_digest,'schema_migration_authorized':False,'started':False}
    (output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');return receipt

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('config','package','accounts','output'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--manifest-sha256',required=True);p.add_argument('--phase',choices=('legacy','a','ab'),required=True);a=p.parse_args()
    print(json.dumps(prepare(a.config,a.package,a.manifest_sha256,a.accounts,a.phase,a.output)))
