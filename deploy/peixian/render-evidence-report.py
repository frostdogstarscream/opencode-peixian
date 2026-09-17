"""Render only validated, allowlisted identity fields; never copy raw inspection text."""
import argparse
from pathlib import Path
from evidence_contract import read_json, validate_public, regular, sha


def render(report):
    validate_public(report)
    lines = ['# N3-E 镜像身份更正（自动生成）', '',
             '本次只读采集纠正旧字段分类，不覆盖旧报告，也不声称复原旧时刻现场。', '',
             '更正来源：`' + report['correction_of'] + '`。',
             '采集批次：`' + report['run_id'] + '`。', '',
             '| 对象 | 实际摘要 | 采集来源 |', '|---|---|---|']
    for name, obj in report['image'].items():
        if name == 'image_revision_label':
            continue
        lines.append('| ' + name + ' | `' + obj.get('digest', 'not_applicable') + '` | ' + obj.get('source', obj.get('reason', '')) + ' |')
    lines += ['', 'inspect 原始引用与 archive config 是不同对象。上述值依据归档描述符关系验证，不要求所有 SHA 相同。',
              '', 'Python 源码集合：预期和实际双向核对；不等同整个镜像验证。宿主磁盘源码不证明运行进程已加载版本。',
              '', '回执归属计数：`' + str(report['receipt_counts']) + '`。只读批次不认领历史控制操作。',
              '', '历史未确认记录：' + str(report['historical_unconfirmed']) + '；原操作结果及根因不能由当前状态反推。',
              '', '**正式发布：blocked。** N4/N5、历史残余风险决定和完整运行身份仍需后续证据。', '']
    return '\n'.join(lines)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    text = render(read_json(a.evidence))
    with a.output.open('x', encoding='utf-8') as out:
        out.write(text + '\n证据原始字节 SHA-256：`' + sha(regular(a.evidence).read_bytes()) + '`。\n')
