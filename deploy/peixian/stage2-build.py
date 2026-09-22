"""Build a matched candidate in a new private directory; never start containers."""
import argparse,hashlib,importlib.util,json,os,shutil,subprocess,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

def require(ok,code):
    if not ok:raise ValueError(code)

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def run(args,cwd,env,log):
    with Path(log).open('wb') as f:
        p=subprocess.run(args,cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT)
    require(p.returncode==0,'build_failed:'+Path(log).name)

def copy_dependencies(source,donor,root):
    require(sha(source/'bun.lock')==sha(donor/'bun.lock') and sha(source/'package.json')==sha(donor/'package.json'),'agent_dependency_lock_mismatch')
    package_files=subprocess.check_output(['git','ls-files','*package.json'],cwd=root,text=True).splitlines()
    locations=[Path('.')]+[Path(x).parent for x in package_files if Path(x).parent!=Path('.') and 'peixian-console' not in x]
    copied=[]
    for rel in locations:
        origin=donor/rel/'node_modules';dest=source/rel/'node_modules'
        if not origin.is_dir():continue
        if rel!=Path('.'):require(sha(source/rel/'package.json')==sha(donor/rel/'package.json'),'workspace_dependency_mismatch')
        shutil.copytree(origin,dest,symlinks=True);copied.append(rel.as_posix())
    # Workspace links must resolve inside the new archive, not import old code.
    for rel in copied:
        for base,dirs,files in os.walk(source/rel/'node_modules',followlinks=False):
            for name in dirs+files:
                p=Path(base)/name
                if p.is_symlink():require(donor not in p.resolve().parents,'dependency_points_to_old_source')
    return copied

def build(root,destination,donor,frontend_dependencies,tool_path,bases):
    root=Path(root).resolve();destination=Path(destination).absolute();donor=Path(donor).resolve();frontend_dependencies=Path(frontend_dependencies).resolve()
    require(not destination.exists() and root not in destination.parents,'new_private_destination_required')
    require(not subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True).strip(),'dirty_source')
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    require(set(bases)=={'control','gateway','agent'},'base_image_set')
    for name,value in bases.items():
        metadata=json.loads(subprocess.check_output(['docker','image','inspect',value],text=True))[0]
        require(value==metadata['Id'],'base_must_be_immutable_image_id')
    destination.mkdir(mode=0o700,parents=True);source=destination/'source';source.mkdir();logs=destination/'logs';logs.mkdir()
    archive=destination/'source.tar.gz';subprocess.run(['git','archive','--format=tar.gz','--output',str(archive),revision],cwd=root,check=True)
    with tarfile.open(archive) as t:t.extractall(source,filter='data')
    copied=copy_dependencies(source,donor,root)
    console=source/'packages/peixian-console'
    for f in ('package.json','package-lock.json'):require(sha(console/f)==sha(frontend_dependencies/f),'frontend_dependency_lock_mismatch')
    shutil.copytree(frontend_dependencies/'node_modules',console/'node_modules',symlinks=True)
    env=os.environ.copy();env.update(PATH=tool_path+':/usr/bin:/bin',OPENCODE_VERSION='1.18.30',OPENCODE_CHANNEL='latest',MODELS_DEV_API_JSON=str(source/'packages/opencode/test/tool/fixtures/models-api.json'),HUSKY='0',DOCKER_BUILDKIT='0')
    for key,folder in [('HOME','test-home'),('XDG_CONFIG_HOME','test-config'),('XDG_DATA_HOME','test-data'),('XDG_STATE_HOME','test-state'),('XDG_CACHE_HOME','test-cache')]:
        path=destination/folder;path.mkdir();env[key]=str(path)
    run(['bun','test','test/session/managed-receipt.test.ts'],source/'packages/opencode',env,logs/'agent-receipt-tests.log')
    run(['bun','run','--cwd','packages/core','fix-node-pty'],source,env,logs/'node-pty.log')
    run(['bun','run','script/build.ts','--single','--skip-install','--skip-embed-web-ui'],source/'packages/opencode',env,logs/'agent-build.log')
    run(['bun','run','typecheck'],console,env,logs/'frontend-typecheck.log')
    run(['bun','run','build'],console,env,logs/'frontend-build.log')
    context=destination/'docker-context';context.mkdir()
    for sub in ('control','gateway','shared'):
        shutil.copytree(source/'services/peixian-control'/sub,context/'services/peixian-control'/sub,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(console/'dist',context/'packages/peixian-console/dist')
    agent_context=destination/'agent-context';agent_context.mkdir()
    binaries=list((source/'packages/opencode/dist').glob('opencode-linux-x64/bin/opencode'))
    require(len(binaries)==1,'agent_binary_missing');shutil.copy2(binaries[0],agent_context/'opencode')
    image_ids={}
    for role in ('control','gateway','agent'):
        dockerfile=source/'deploy/peixian'/('Stage2.'+role.capitalize()+'.Dockerfile');ctx=agent_context if role=='agent' else context
        shutil.copy2(dockerfile,ctx/('Dockerfile.'+role));tag='peixian-stage2-'+role+':'+revision[:12]
        exists=subprocess.run(['docker','image','inspect',tag],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        require(exists.returncode!=0,'existing_image_tag_preserved')
        run(['docker','build','--network','none','--build-arg','BASE_IMAGE='+bases[role],'--build-arg','SOURCE_REVISION='+revision,'-f',str(ctx/('Dockerfile.'+role)),'-t',tag,str(ctx)],source,env,logs/(role+'-image.log'))
        image_ids[role]=json.loads(subprocess.check_output(['docker','image','inspect',tag],text=True))[0]['Id']
    spec=importlib.util.spec_from_file_location('stage2_artifact',root/'deploy/peixian/stage2-artifact.py');artifact=importlib.util.module_from_spec(spec);spec.loader.exec_module(artifact)
    stamp={'source_revision':revision,'tree_sha256':artifact.tree_digest(console/'dist'),'package_lock_sha256':sha(console/'package-lock.json')}
    (destination/'frontend-stamp.json').write_text(json.dumps(stamp,indent=2)+'\n')
    (destination/'images.json').write_text(json.dumps(image_ids,indent=2)+'\n')
    (destination/'rollback-images.json').write_text(json.dumps(bases,indent=2)+'\n')
    receipt={'source_revision':revision,'source_archive_sha256':sha(archive),'agent_binary_sha256':sha(agent_context/'opencode'),'agent_dependency_lock_sha256':sha(source/'bun.lock'),'dependency_workspaces':copied,'frontend':stamp,'images':image_ids,'base_images':bases,'deployment_performed':False}
    (destination/'build-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');return receipt

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--output',type=Path,required=True);p.add_argument('--dependency-donor',type=Path,required=True);p.add_argument('--frontend-dependencies',type=Path,required=True);p.add_argument('--tool-path',required=True);p.add_argument('--base-images',type=Path,required=True);a=p.parse_args()
    print(json.dumps(build(a.root,a.output,a.dependency_donor,a.frontend_dependencies,a.tool_path,json.loads(a.base_images.read_text())),indent=2))
