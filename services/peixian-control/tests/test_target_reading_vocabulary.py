"""Reading vocabulary must not erase an unsupported target or scope."""
import pytest
from control import task_targets

@pytest.mark.parametrize('text', ['整理原始资金流水', '把资金流水列出来', '请看收支情况', '资金资料有哪些', '统计资金记录数', '整理夜晚活动', '夜间记录有几条', '查看同框资料', '列出明确同行记录', '看看同框时间', '整理同行观测', '查看夜间记录', '核对车辆通行'])
def test_reading_words_preserve_default_subject(monkeypatch,text):
    monkeypatch.setattr(task_targets,'visible',lambda *a: set())
    value=task_targets.resolve(None,'u','s','DEMO-CASE-GAMBLING',text,['funds'])
    assert value['status']=='resolved'
    assert value['target_mode']=='scenario_subject'

@pytest.mark.parametrize('text', ['把陌生人的原始资金流水列出来', '查看陌生人的资金资料', '查看DEMO-UNKNOWN资金', '查看最近三天资金', '查看2026-09-01资金', '查看这个账户资金', '查看两个人资金', '查看资金xyz', '查看张某同行记录'])
def test_reading_words_do_not_hide_unsupported_input(monkeypatch,text):
    monkeypatch.setattr(task_targets,'visible',lambda *a: set())
    value=task_targets.resolve(None,'u','s','DEMO-CASE-GAMBLING',text,['funds'])
    assert value['status']!='resolved'
