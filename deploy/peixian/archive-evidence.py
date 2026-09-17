"""Offline archive evidence only; cannot establish current container or Worker identity."""
import argparse
import hashlib
import json
from pathlib import Path
from evidence_contract import archive_identity, read_json, regular, require, sha, utc, write_new


def collect(package):
    manifest = read_json(package / 'release-manifest.json')
    identities = {}
    for role, tag in manifest['requested_images'].items():
        identities[role] = archive_identity(package / 'images.tar', tag, {'os': 'linux', 'architecture': 'amd64'})
    with regular(package / 'images.tar').open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    return {'evidence_format': 1, 'status': 'archive_verified', 'collected_at': utc(),
            'correction_of': 'deploy/peixian/reports/n3-local-evidence.json',
            'source_commit': manifest['source_commit'], 'archive_sha256': digest,
            'package_manifest_sha256': sha(regular(package / 'release-manifest.json').read_bytes()),
            'identities': identities, 'runtime_collection': 'not_collected_archive_only',
            'historical_instant': 'not_reconstructed', 'production_status': 'blocked'}


def render(value):
    lines = ['# N3-E 归档对象更正（自动生成）', '',
             '本次仅检查既有镜像归档，未重新观察运行容器；不覆盖旧证据。', '',
             '| 组件 | 对象类型 | 原始字节 SHA-256 |', '|---|---|---|']
    for role, objects in value['identities'].items():
        for name, obj in objects.items():
            lines.append('| ' + role + ' | ' + name + ' | `' + obj.get('digest', 'not_applicable') + '` |')
    lines += ['', '旧 JSON 的 image_config_id 取自 Docker inspect Id，不是从归档 config 字节计算。',
              '本归档描述符链证明旧 Markdown 的 config 值有归档依据；旧 JSON 字段名称需要更正，不能据此断言部署了错误镜像。',
              '当前运行引用和 Worker 加载版本仍未重新验证；历史现场不能完全复原。',
              '', '归档原始字节 SHA-256：`' + value['archive_sha256'] + '`。',
              '源码归档提交：`' + value['source_commit'] + '`。',
              '**PR-6 发布状态：blocked。**', '']
    return '\n'.join(lines)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--markdown', type=Path, required=True)
    a = p.parse_args()
    require(not a.output.exists() and not a.markdown.exists(), 'output_exists')
    result = collect(a.package)
    write_new(a.output, result)
    with a.markdown.open('x', encoding='utf-8') as output:
        output.write(render(result))
    print(json.dumps({'status': result['status'], 'runtime_collection': result['runtime_collection']}))
