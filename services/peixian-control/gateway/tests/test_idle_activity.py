from gateway.admission import AdmissionGate


def test_short_work_and_completion_restart_idle_clock_but_passive_reads_do_not():
    clock=[0.]
    gate=AdmissionGate('runtime',1,clock=lambda:clock[0])
    clock[0]=600
    assert gate.snapshot()['idle_proof']['idle_seconds']==600
    passive=gate.register('passive_read'); gate.finish(passive)
    assert gate.snapshot()['idle_proof']['sequence']==0
    task=gate.register('parsing')
    clock[0]=1200
    assert gate.snapshot()['idle_proof']['idle_seconds']==0
    gate.finish(task)
    assert gate.snapshot()['idle_proof']['sequence']==2
    clock[0]=1210
    assert gate.snapshot()['idle_proof']['idle_seconds']==10


def test_source_sequence_detects_work_between_polls_and_stale_observation_resets():
    clock=[10.]
    gate=AdmissionGate('runtime',1,clock=lambda:clock[0])
    gate.source('native',{},token=('boot',0))
    clock[0]=11;gate.source('native',{},token=('boot',0))
    assert gate.snapshot()['idle_proof']['idle_seconds']==1
    clock[0]=12;gate.source('native',{},token=('boot',2))
    assert gate.snapshot()['idle_proof']['idle_seconds']==0
    clock[0]=20
    assert not gate.snapshot()['idle_proof']['complete']
    gate.source('native',{},token=('boot',2))
    assert gate.snapshot()['idle_proof']['idle_seconds']==0
    clock[0]=21;gate.source('native',{},token=('new-boot',0))
    assert gate.snapshot()['idle_proof']['idle_seconds']==0
    clock[0]=5
    assert not gate.snapshot()['idle_proof']['complete']


def test_legacy_count_zero_is_not_idle_proof():
    gate=AdmissionGate('runtime',1)
    gate.source('native',{})
    assert gate.snapshot()['activity']['idle']
    assert not gate.snapshot()['idle_proof']['complete']
