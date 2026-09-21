import copy
import importlib.util
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('release_check',ROOT/'deploy/peixian/stage1-release-check.py')
check=importlib.util.module_from_spec(spec);spec.loader.exec_module(check)

def release():return check.load(ROOT/'specs/seven-plugins-pr1-4-release.json')

def test_recorded_release_and_reproducible_archives():
    check.validate(ROOT,ROOT/'specs/seven-plugins-pr1-4-release.json')

@pytest.mark.parametrize('mutation,code',[
    (lambda d:d['historical_runs'].update(new_runs=7),'run_total_mismatch'),
    (lambda d:d['model_budget'].update(round_total=28),'model_budget_mismatch'),
    (lambda d:d['model_requests'][1].update(client_request_id=d['model_requests'][0]['client_request_id']),'duplicate_request_id'),
    (lambda d:d['model_requests'][1].update(run_id=d['model_requests'][0]['run_id']),'admitted_run_mismatch'),
    (lambda d:d['disabled_check'].update(runs_after=78),'disabled_check_count_mismatch'),
])
def test_count_drift_fails(mutation,code):
    data=release();mutation(data)
    with pytest.raises(ValueError,match=code):check.check_counts(data)

@pytest.mark.parametrize('mutation',[
    lambda d:d['runtime_states'][0].update(status='draining'),
    lambda d:d['runtime_states'][0].update(desired=999),
    lambda d:d['legacy'].update(grants=1),
])
def test_readiness_or_legacy_drift_fails(mutation):
    data=release();mutation(data)
    with pytest.raises(ValueError):check.check_runtime(data)

@pytest.mark.parametrize('field,code',[
    ('source','source_not_ancestor'),('plugin','plugin_hash_mismatch'),
    ('skill','skill_hash_mismatch'),('checksum','checksum_mismatch'),
])
def test_corrupt_release_cannot_emit_artifact(tmp_path,field,code):
    import hashlib,json,shutil,subprocess,sys
    source=ROOT/'specs'
    for line in (source/'seven-plugins-pr1-4-SHA256SUMS.txt').read_text().splitlines():
        name=line.split('  ',1)[1];shutil.copyfile(source/name,tmp_path/name)
    shutil.copyfile(source/'seven-plugins-pr1-4-SHA256SUMS.txt',tmp_path/'seven-plugins-pr1-4-SHA256SUMS.txt')
    path=tmp_path/'seven-plugins-pr1-4-release.json';data=json.loads(path.read_text())
    if field=='source':data['source_revision']='0'*40
    if field=='plugin':data['plugins'][0]['sha256']='0'*64
    if field=='skill':data['methods'][0]['content_sha256']='0'*64
    if field=='checksum':data['evidence_scope']='modified without updating checksum'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match=code):check.validate(ROOT,path)
    output=tmp_path/'must-not-exist.json'
    result=subprocess.run([sys.executable,str(ROOT/'deploy/peixian/stage1-release-check.py'),
        '--root',str(ROOT),'--manifest',str(path),'--output',str(output)],capture_output=True)
    assert result.returncode!=0 and not output.exists()
