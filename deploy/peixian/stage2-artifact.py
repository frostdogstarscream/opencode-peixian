"""Strict, data-free Stage2 candidate assembly and verification. Never deploy."""
import argparse,hashlib,importlib.util,json,os,re,shutil,subprocess,tarfile,tempfile
from pathlib import Path,PurePosixPath
ROLES=('control','gateway','agent')
MODULES=('funds','calls','portrait','composite','night','vehicle','lookup')
TAG='stage2-dual-agent-v1.0.0-rc1'

def require(ok,code):
    if not ok:raise ValueError(code)

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def command(args,**kwargs):
    return subprocess.check_output(args,text=True,**kwargs).strip()

def inventory(root):
    result={}
    for p in sorted(Path(root).rglob('*')):
        require(not p.is_symlink(),'symlink_in_artifact')
        if p.is_file():result[p.relative_to(root).as_posix()]=digest(p)
    return result

def tree_digest(root):
    return hashlib.sha256(json.dumps(inventory(root),sort_keys=True,separators=(',',':')).encode()).hexdigest()

def image_identity(value,revision,role):
    require(re.fullmatch(r'sha256:[0-9a-f]{64}',value.get('Id','')),'image_digest')
    labels=value.get('Config',{}).get('Labels') or {}
    require(labels.get('org.opencontainers.image.revision')==revision,'image_source_mismatch')
    if role=='control':require(labels.get('org.peixian.control.schema.max')=='9','image_schema_mismatch')
    if role=='agent':require('durable_run_v1' in labels.get('org.peixian.runtime.capabilities','').split(','),'agent_protocol')
    return {'image_id':value['Id'],'source_revision':revision,'repo_digests':value.get('RepoDigests',[])}

def validate_manifest(folder,expected_digest=None):
    folder=Path(folder)
    if expected_digest is not None:require(digest(folder/'release-manifest.json')==expected_digest,'untrusted_manifest')
    m=json.loads((folder/'release-manifest.json').read_text(encoding='utf-8'))
    require(m.get('schema')=='peixian.stage2-release' and m.get('version')=='1.0','manifest_schema')
    require(m.get('schema_version')==9 and m.get('data_environment')=='synthetic','release_scope')
    require(m.get('tag')==TAG and re.fullmatch('[0-9a-f]{40}',m.get('source_revision','')),'release_identity')
    require(m.get('source_matches_commit') is True and m.get('contains_runtime_data') is False,'source_identity')
    require(set(m.get('images',{}))==set(ROLES),'image_set')
    require(set(m.get('plugins',{}))=={'peixian-records-'+x for x in MODULES},'plugin_set')
    require(bool(m.get('skills')) and bool(m.get('registries')),'catalog_set')
    files=m.get('files',{});require(isinstance(files,dict) and bool(files),'file_set')
    for name,h in files.items():
        path=PurePosixPath(name)
        require(not path.is_absolute() and '..' not in path.parts and '\\' not in name and path.as_posix()==name,'unsafe_artifact_path')
        require(re.fullmatch('[0-9a-f]{64}',h) is not None,'file_digest')
    actual=inventory(folder);actual.pop('release-manifest.json',None)
    require(actual==files,'artifact_inventory_mismatch')
    for pid,plugin in m['plugins'].items():
        version=plugin.get('version','');require(re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',version) is not None,'plugin_version')
        require(files.get('plugins/'+pid+'-'+version+'.zip')==plugin.get('sha256'),'plugin_digest')
    for sid,skill in m['skills'].items():
        require(re.fullmatch('[a-zA-Z0-9_.-]+',sid) is not None and files.get('skills/'+sid+'.md')==skill.get('sha256'),'skill_digest')
    require(m['registries']==inventory(folder/'registries'),'registry_digest')
    required={'source.tar.gz','frontend.tar.gz','openapi.json','rollback-manifest.json','sbom/source.cdx.json'}
    for role,value in m['images'].items():
        require(re.fullmatch(r'sha256:[0-9a-f]{64}',value.get('image_id','')) is not None and value.get('source_revision')==m['source_revision'],'image_identity')
        required|={f'images/{role}.tar',f'sbom/{role}.cdx.json'}
    require(required<=set(files),'required_artifact_missing')
    for file in [x for x in required if x.endswith('.cdx.json')]:
        sbom=json.loads((folder/file).read_text(encoding='utf-8'));require(sbom.get('bomFormat')=='CycloneDX' and bool(sbom.get('components')),'sbom_invalid')
    rollback=json.loads((folder/'rollback-manifest.json').read_text(encoding='utf-8'))
    require(rollback.get('schema_version')==9 and rollback.get('restore_to_empty_target') is True and rollback.get('downgrade_database') is False,'rollback_contract')
    require(rollback.get('requires_full_backup') is True,'rollback_backup')
    return m

def assemble(root,revision,frontend,stamp,images,output,syft,rollback_images):
    root=Path(root).resolve();output=Path(output).absolute();frontend=Path(frontend).resolve()
    require(not output.exists(),'existing_artifact_preserved')
    require(root not in output.parents,'output_inside_source')
    require(command(['git','rev-parse','HEAD'],cwd=root)==revision,'source_head_mismatch')
    require(not command(['git','status','--porcelain'],cwd=root),'dirty_source')
    require(set(images)==set(ROLES),'image_set')
    metadata=json.loads(Path(stamp).read_text(encoding='utf-8'));require(metadata.get('source_revision')==revision and metadata.get('tree_sha256')==tree_digest(frontend),'frontend_source_mismatch')
    require(set(rollback_images)==set(ROLES) and all(re.fullmatch(r'sha256:[0-9a-f]{64}',x) for x in rollback_images.values()),'rollback_images')
    identities={role:image_identity(json.loads(command(['docker','image','inspect',images[role]]))[0],revision,role) for role in ROLES}
    output.mkdir(mode=0o700,parents=True)
    for d in ('images','plugins','skills','registries','sbom'):(output/d).mkdir()
    # Every deploy/source file comes from Git, never from a second working tree.
    subprocess.run(['git','archive','--format=tar.gz','--output',str(output/'source.tar.gz'),revision],cwd=root,check=True)
    with tempfile.TemporaryDirectory(prefix='stage2-source-',dir=output.parent) as temp:
        src=Path(temp)
        with tarfile.open(output/'source.tar.gz') as t:t.extractall(src,filter='data')
        package=src/'deploy/peixian/examples/seven_data_plugins/package.py'
        spec=importlib.util.spec_from_file_location('frozen_plugin_package',package);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        plugins={p['id']:p for p in module.build(output/'plugins')}
        methods=json.loads((src/'services/peixian-control/control/official_methods.json').read_text(encoding='utf-8'));skills={}
        for skill in methods['skills']:
            require(re.fullmatch('[a-zA-Z0-9_.-]+',skill['id']) is not None,'unsafe_skill_id')
            file=output/'skills'/(skill['id']+'.md');file.write_text(skill['content'],encoding='utf-8')
            require(digest(file)==skill['sha256'],'skill_digest')
            skills[skill['id']]={k:skill[k] for k in ('version','state','sha256')}
        regs=src/'services/peixian-control/control/developer_registry/data'
        for f in regs.glob('*.json'):shutil.copyfile(f,output/'registries'/f.name)
        for f in (src/'services/peixian-control/control/agents').rglob('*.json'):
            name='agent-'+f.name;require(not (output/'registries'/name).exists(),'duplicate_registry');shutil.copyfile(f,output/'registries'/name)
        shutil.copyfile(src/'specs/stage2-pr9a-openapi.json',output/'openapi.json')
        env=os.environ.copy();env['SYFT_CHECK_FOR_APP_UPDATE']='false'
        subprocess.run([str(syft),'scan','dir:'+str(src),'-q','-o','cyclonedx-json='+str(output/'sbom/source.cdx.json')],env=env,check=True)
    with tarfile.open(output/'frontend.tar.gz','w:gz') as t:
        for name in inventory(frontend):t.add(frontend/name,arcname=name,recursive=False)
    for role,item in identities.items():
        subprocess.run(['docker','image','save','-o',str(output/'images'/f'{role}.tar'),item['image_id']],check=True)
        env=os.environ.copy();env['SYFT_CHECK_FOR_APP_UPDATE']='false'
        subprocess.run([str(syft),'scan','docker:'+item['image_id'],'-q','-o','cyclonedx-json='+str(output/'sbom'/f'{role}.cdx.json')],env=env,check=True)
    rollback={'previous_image_ids':rollback_images,'previous_set_requires_preupgrade_backup_restore':True,'schema_version':9,'restore_to_empty_target':True,'downgrade_database':False,'requires_full_backup':True,'required_materials':['control_database','user_volumes','published_configuration','host_execution_state','matching_keys','deployment_configuration','image_manifest'],'rule':'Use a compatible v9 image set, or restore a complete pre-upgrade backup into an empty namespace. Never connect old v6/v8 writers to v9.'}
    (output/'rollback-manifest.json').write_text(json.dumps(rollback,indent=2)+'\n',encoding='utf-8')
    require(command(['git','rev-parse','HEAD'],cwd=root)==revision and not command(['git','status','--porcelain'],cwd=root),'source_changed_during_assembly')
    m={'schema':'peixian.stage2-release','version':'1.0','schema_version':9,'tag':TAG,'source_revision':revision,'source_matches_commit':True,'contains_runtime_data':False,'data_environment':'synthetic','images':identities,'frontend':metadata,'plugins':plugins,'skills':skills,'registries':inventory(output/'registries'),'sbom_scope':'Runtime filesystem inventories plus source lockfiles; opaque compiled dependencies may need source-level inspection. This is not a vulnerability clearance.','files':inventory(output)}
    (output/'release-manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    validate_manifest(output);return m

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--verify',type=Path);p.add_argument('--manifest-sha256');p.add_argument('--root',type=Path);p.add_argument('--revision');p.add_argument('--frontend',type=Path);p.add_argument('--frontend-stamp',type=Path);p.add_argument('--images',type=Path);p.add_argument('--rollback-images',type=Path);p.add_argument('--output',type=Path);p.add_argument('--syft',type=Path);a=p.parse_args()
    if a.verify:
        if not a.manifest_sha256:p.error('verification requires the manifest SHA256 from the trusted release receipt')
        m=validate_manifest(a.verify,a.manifest_sha256)
    else:
        if not all((a.root,a.revision,a.frontend,a.frontend_stamp,a.images,a.output,a.syft,a.rollback_images)):p.error('assembly requires source, frontend, image identities, output and pinned syft')
        m=assemble(a.root,a.revision,a.frontend,a.frontend_stamp,json.loads(a.images.read_text(encoding='utf-8')),a.output,a.syft,json.loads(a.rollback_images.read_text(encoding='utf-8')))
    print(json.dumps({'status':'verified','source_revision':m['source_revision'],'tag':m['tag'],'files':len(m['files'])}))
