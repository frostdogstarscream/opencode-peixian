"""Deterministic, version-bound timeline. Only called after canonical fact validation."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from hashlib import sha256
from itertools import groupby

TZ = timezone(timedelta(hours=8))
ALIASES = {"DEMO-MEMBER-ORCHID": "对象甲", "DEMO-MEMBER-QUARTZ": "对象乙", "DEMO-MEMBER-SAFFRON": "对象丙", "DEMO-MEMBER-INDIGO": "对象丁"}
KINDS = {"same_frame": "同框观测", "same_trip": "明确同行", "same_vehicle": "明确同乘"}
OBSERVATIONS = {"alone": "明确独行观测（仅本片段）", "accompanied": "明确同行观测", "unknown": "同行状态无法判断"}
RELATIONS = {"member_to_account": "对象与账户对应", "member_to_contact": "对象与联系编号对应", "member_to_vehicle": "对象与车辆对应"}
LEGEND = "虚线箭头仅表示时间先后，不表示因果关系；同一时刻不区分先后。"


def stamp(value):
    try:
        dt = datetime.fromisoformat(value)
        return dt.astimezone(TZ) if dt.tzinfo else None
    except (ValueError, TypeError):
        return None


def label(value):
    # Display-only punctuation normalization; original fields remain in the event list.
    unsafe = dict(zip('"\\<>`#%&{}[]|', '＂＼＜＞｀＃％＆｛｝［］｜'))
    return ''.join(unsafe.get(c, c) if ord(c) >= 32 else ' ' for c in str(value))


def compile_pages(nodes):
    nodes = sorted(nodes, key=lambda n: (n['time'] is None, n['time'] or '', n['id']))
    for i, node in enumerate(nodes):
        node['number'] = '事件' + str(i + 1).zfill(2)
    pages = []
    for start in range(0, len(nodes), 20):
        rows = nodes[start:start + 20]; groups = []; edges = []
        for key, values in groupby(rows, key=lambda n: n['group']):
            group = list(values); groups.append({'title': key, 'node_ids': [n['id'] for n in group]})
        timed = [n for n in rows if n['time']]
        slots = [list(values) for _, values in groupby(timed, key=lambda n: n['time'])]
        for previous, current in zip(slots, slots[1:]):
            edges.extend({'from': a['id'], 'to': b['id'], 'kind': 'chronological'} for a in previous for b in current)
        lines = ['flowchart TB']
        for i, group in enumerate(groups):
            lines.append('subgraph g' + str(i) + '["' + label(group['title']) + '"]')
            for n in rows:
                if n['id'] not in group['node_ids']: continue
                short = n['event'] if len(n['event']) <= 30 else n['event'][:29] + '…'
                text = [n['number'] + ' · ' + (n['time'][11:16] if n['time'] else '时间未明确'), n['subject'], short]
                lines.append(n['id'] + '("' + '\n'.join(label(t) for t in text) + '")')
            lines.append('end')
        lines.extend(e['from'] + ' -.-> ' + e['to'] for e in edges)
        pages.append({'number': len(pages) + 1, 'groups': groups, 'nodes': rows, 'edges': edges, 'mermaid': '\n'.join(lines)})
    return pages


def build(result, table, data, places):
    context = data['scenarios'].get(table['scenario_id'])
    base = {'version': '1.0', 'status': 'unavailable', 'run_id': None, 'scenario_id': table['scenario_id'],
            'timezone': 'Asia/Shanghai', 'window_start': table['window_start'], 'window_end': table['window_end'],
            'scenario_snapshot_id': table['scenario_snapshot_id'], 'records_snapshot_id': table['records_snapshot_id'],
            'rule_version': table['rule_version'], 'synthetic': table['synthetic'], 'pages': [], 'total_nodes': 0,
            'legend': LEGEND, 'aliases': [{'name': v, 'ref': k} for k, v in ALIASES.items()], 'missing': list(result['missing'])}
    if not context or context['snapshot_id'] != table['scenario_snapshot_id'] or context['records_snapshot_id'] != table['records_snapshot_id']:
        base['missing'].append('资料版本不兼容，不能生成事件图。'); return base
    cards = {c['id']: c for c in result['cards']}; nodes = []
    from .scenario_versions import supported_sources
    valid_sources = supported_sources(context, cards)
    base['aliases'] = [{'name': ALIASES.get(context['subject_ref'], context['subject_ref']), 'ref': context['subject_ref']}]
    for module in context['required_modules']:
        source = data['records'][module]
        if source['snapshot_id'] != table['records_snapshot_id']:
            base['missing'].append('来源快照不匹配：' + module); continue
        for row in source['records']:
            rid = row['record_id']
            if rid not in cards or cards[rid]['snapshot_id'] != table['records_snapshot_id']: continue
            card = cards[rid]; dt = stamp(row.get('occurred_at')); subject = ALIASES.get(context['subject_ref'], context['subject_ref'])
            event = ''; references = [rid]; notes = []
            if module == 'night': event = '夜间观测'
            if module == 'portrait':
                event = KINDS.get(row.get('kind'), '观测类型未明确')
                other = row.get('co_member_ref') if row.get('member_ref') == context['subject_ref'] else row.get('member_ref')
                if other: subject += ' 与 ' + ALIASES.get(other, other)
            if module == 'funds':
                amount = row.get('amount_minor')
                if type(amount) is not int:
                    base['missing'].append(rid + ' 金额单位不明确'); continue
                direction = {'credit': '收入', 'debit': '支出'}.get(row.get('direction'), '方向未明确')
                event = direction + ' ' + format(Decimal(amount) / Decimal(100), '.2f') + ' 元'
                notes = ['账户：' + row['group_ref'], '对手账户：' + row['counterparty_ref'], '逐条原始流水，不配对合并。']
            if module == 'vehicle':
                event = '车辆' + {'inbound': '驶入', 'outbound': '驶出'}.get(row.get('direction'), '通行')
                notes = ['车辆编号：' + row['group_ref'], '设备编号：' + row.get('device_ref', ''), '不同时间使用同一车辆不表示同乘。']
            if module == 'lookup':
                event = RELATIONS.get(row.get('kind'), '已有对应关系')
                notes = ['对应引用：' + row['member_ref']]
                references += row.get('source_record_ids', [])
            for fact in context['facts']:
                if fact['record_id'] in cards and rid in fact['source_record_ids'] and fact.get('observation') in OBSERVATIONS:
                    event += '；' + OBSERVATIONS[fact['observation']]
                    references += [fact['record_id']] + ([fact['source_document']] if fact.get('source_document') else [])
            for place in places.get(context['scenario_id'], {}).get('places', []):
                if rid in place['source_ids'] and all(x in valid_sources for x in place['source_ids']):
                    notes += [place['label'] + '：' + place['relationship'] + '（未提供距离）']; references += place['source_ids']
            period = ('凌晨' if dt.hour < 6 else '日间' if dt.hour < 18 else '晚间' if dt.hour < 22 else '夜间') if dt else ''
            nodes.append({'id': 'n' + sha256(rid.encode()).hexdigest()[:16], 'time': dt.isoformat() if dt else None,
                          'group': dt.strftime('%Y-%m-%d') + ' · ' + period if dt else '时间未明确',
                          'subject': subject, 'subject_ref': context['subject_ref'], 'event': event, 'category': module,
                          'source_ids': list(dict.fromkeys(references)), 'message_id': card['message_id'], 'notes': notes})
    # Registration window is a contextual range, not an observed person event.
    case_fact = next((f for f in context['facts'] if f['record_id'] in cards and f['record_id'] == ('demo54' if context['snapshot_id'] == 'demo1003' else 'DEMO-CTX-T01')), None)
    base['case_window'] = context['case_window'] if context['scenario_id'] == 'DEMO-CASE-THEFT' and case_fact else []
    base['case_source_ids'] = [case_fact['record_id'], case_fact['source_document']] if base['case_window'] else []
    base['pages'] = compile_pages(nodes); base['total_nodes'] = len(nodes)
    base['status'] = ('ready' if result['status'] == 'complete' else 'partial') if nodes else 'empty'
    return base


def schema():
    text={'type':'string'}
    def array(value):return {'type':'array','items':value}
    def obj(properties,required=None):return {'type':'object','properties':properties,'required':list(properties) if required is None else required,'additionalProperties':False}
    node=obj({**{k:text for k in ('id','number','group','subject','subject_ref','event','category','message_id')},'time':{'type':['string','null']},'source_ids':array(text),'notes':array(text)})
    page=obj({'number':{'type':'integer','minimum':1},'groups':array(obj({'title':text,'node_ids':array(text)})),'nodes':{**array(node),'maxItems':20},'edges':array(obj({'from':text,'to':text,'kind':{'const':'chronological'}})),'mermaid':text})
    fields={**{k:text for k in ('scenario_id','timezone','window_start','window_end','scenario_snapshot_id','records_snapshot_id','rule_version','legend')},'version':{'const':'1.0'},'status':{'enum':['ready','partial','empty','unavailable']},'run_id':{'type':['string','null']},'synthetic':{'type':'boolean'},'total_nodes':{'type':'integer','minimum':0},'pages':array(page),'aliases':array(obj({'name':text,'ref':text})),'missing':array(text),'case_window':array(text),'case_source_ids':array(text)}
    return obj(fields,[k for k in fields if k not in ('case_window','case_source_ids')])
