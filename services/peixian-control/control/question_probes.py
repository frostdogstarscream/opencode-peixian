"""Option-count probes for platform question cards.

Probes query the widest offered scope before the user chooses, only to label each
option with a record count. Results never enter native_calls, model input or reports;
the chosen option is still queried normally afterwards.
"""
import copy
import math
from datetime import timedelta

from shared import theft_provider_v2 as adapter

VERSION = 'question-probe-v1'
MAX_PROBES = 6
MAX_CASES = 5
MAX_CENTERS = 3
CASE_DAYS = 15
UNITS = {'tracks': '轨迹 {} 条', 'incidents': '警情 {} 起', 'captures': '抓拍 {} 人',
         'night': '夜间记录 {} 条', 'community': '跨小区记录 {} 条'}
BUCKETED = {'tracks', 'incidents'}


def _distance(lon1, lat1, lon2, lat2):
    if None in (lon1, lat1, lon2, lat2):
        return None
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 6371000.0 * math.asin(math.sqrt(a))


def _find(spec, field, header=None):
    for index, question in enumerate(spec.get('questions') or []):
        if question.get('field') == field and (header is None or question.get('header') == header):
            return index
    return None


def _labels(spec, index):
    values = spec.get('values') or {}
    if index is None:
        return []
    return [o['label'] for o in spec['questions'][index].get('options') or [] if o['label'] in values]


def _windows(spec, index):
    values = spec.get('values') or {}
    return {label: (values[label]['start'], values[label]['end']) for label in _labels(spec, index)
            if isinstance(values[label], dict) and {'start', 'end'} <= values[label].keys()}


def _freeze(store, uid, sid, applied, kind, context, start=None, end=None, radius=None, refs=None, point=None):
    """Build a probe plan exactly as a normal call would, then freeze it against the contract."""
    from .native_tool_scope import resolve_arguments, arguments, source_values
    from . import provider_contracts
    work = copy.deepcopy(context)
    work['source_refs'] = copy.deepcopy(refs if refs is not None else work.get('source_refs') or [])
    scope = {k: v for k, v in (('start', start), ('end', end), ('radius_m', radius)) if v is not None}
    work.setdefault('confirmed', {}).update(scope)
    work.setdefault('user_conditions', {}).update(scope)
    if kind == 'captures':
        work['capture_conditions'] = {**(work.get('capture_conditions') or {}), **scope}
    if kind == 'incidents' and start and end:
        work['incident_window'] = {'start': start, 'end': end}
    args = {}
    if point:
        work['source_refs'] = []
        args = {'lon': point[0], 'lat': point[1], 'radius_m': radius, 'start': start, 'end': end}
    query = arguments(kind, resolve_arguments(kind, args, work), work)
    identities = {}
    if work['source_refs']:
        derived, identities = source_values(store, uid, sid, kind, work)
        query.update(derived)
    elif kind in adapter.PERSON:
        identity = work['confirmed'].get('person_identity')
        ref = adapter.person_ref(adapter.person_id(identity), store.worker_key.encode(), uid + '/' + sid)
        query['person_ref'] = ref
        identities[ref] = identity
    return provider_contracts.freeze(store, uid, kind, query, identities, applied)


def _job(state, plans, build, kind, purposes, **scope):
    key = [kind, scope.get('start'), scope.get('end'), scope.get('radius'), scope.get('point'),
           adapter.canonical(scope.get('refs') or [])]
    same = next((j for j in state['jobs'].values() if j['key'] == key), None)
    if same:
        same['purposes'] += purposes
        return
    if len(state['jobs']) >= MAX_PROBES:
        return
    job_id = 'probe' + str(len(state['jobs']) + 1)
    job = {'key': key, 'kind': kind, 'purposes': purposes, 'point': scope.get('point'),
           'window': [scope.get('start'), scope.get('end')], 'radius': scope.get('radius'), 'status': 'pending'}
    state['jobs'][job_id] = job
    try:
        plan = build(kind, scope)
    except Exception:
        job['status'] = 'unavailable'
        return
    query = plan.get('query') or {}
    if 'lon' in query and 'lat' in query:
        job['origin'] = [float(query['lon']), float(query['lat'])]
    plans.append({'id': job_id, 'plan': plan})


def start(spec, context, store, uid, sid, applied):
    """Record probe state on the pending spec; return the plans the gateway should run."""
    from .native_precheck_questions import source_match, _parse_cjsj
    state = {'version': VERSION, 'round': 1, 'jobs': {}, 'units': {}, 'notes': {}}
    plans = []
    values = spec.get('values') or {}
    confirmed = context.get('confirmed') or {}
    kind = spec.get('kind')
    person_case = context.get('direction') == 'person_to_case' and kind in ('tracks', 'night', 'community')
    probe_kind = 'tracks' if person_case else kind

    def build(job_kind, scope):
        return _freeze(store, uid, sid, applied, job_kind, context, scope.get('start'), scope.get('end'),
                       scope.get('radius'), scope.get('refs'), scope.get('point'))

    cases = _find(spec, 'source', '选择案件') if kind == 'captures' else None
    time_q, radius_q = _find(spec, 'time_window'), _find(spec, 'radius_m')
    windows = _windows(spec, time_q)
    widest = (min(s for s, _ in windows.values()), max(e for _, e in windows.values())) if windows else None
    if not widest and {'start', 'end'} <= confirmed.keys():
        widest = (confirmed['start'], confirmed['end'])
    radii = {label: values[label] for label in _labels(spec, radius_q) if isinstance(values[label], int)}
    largest = max(radii.values()) if radii else confirmed.get('radius_m')
    refs = [spec['auto_source_ref']] if spec.get('auto_source_ref') else None

    if cases is not None:
        state['units'][cases] = UNITS['captures']
        held = context.get('capture_conditions') or {}
        for label in _labels(spec, cases)[:MAX_CASES]:
            ref = values[label].get('source_ref')
            anchor = _parse_cjsj((source_match(store, uid, sid, ref) or {}).get('cjsj'))
            if {'start', 'end'} <= held.keys():
                window = (held['start'], held['end'])
            elif anchor:
                window = ((anchor - timedelta(days=CASE_DAYS)).strftime('%Y-%m-%d %H:%M:%S'),
                          anchor.strftime('%Y-%m-%d %H:%M:%S'))
            else:
                continue
            _job(state, plans, build, 'captures', [['option', cases, label]], start=window[0], end=window[1],
                 radius=held.get('radius_m') or max(v for _, v in _radius_options()), refs=[ref])
    elif person_case:
        if widest:
            purposes = ([['time', time_q]] if windows else []) + ([['centres', radius_q]] if radii else [])
            if purposes:
                state['units'][time_q] = UNITS['tracks']
                if radii:
                    state['units'][radius_q] = UNITS['incidents']
                    label = next((l for l, w in windows.items() if w == widest), None)
                    state['notes'][radius_q] = f'按{label or "所选时间"}停留点统计'
                _job(state, plans, build, 'tracks', purposes, start=widest[0], end=widest[1])
    elif probe_kind in BUCKETED:
        state['units'][time_q] = state['units'][radius_q] = UNITS[probe_kind]
        purposes = ([['time', time_q]] if windows else []) + ([['radius', radius_q]] if radii else [])
        if purposes and widest:
            _job(state, plans, build, probe_kind, purposes, start=widest[0], end=widest[1],
                 radius=largest, refs=refs)
    elif probe_kind in UNITS:
        state['units'][time_q] = state['units'][radius_q] = UNITS[probe_kind]
        for label, (left, right) in windows.items():
            _job(state, plans, build, probe_kind, [['option', time_q, label]], start=left, end=right,
                 radius=largest, refs=refs)
        for label, radius in radii.items():
            if widest:
                _job(state, plans, build, probe_kind, [['option', radius_q, label]], start=widest[0],
                     end=widest[1], radius=radius, refs=refs)
    # The spec is stored as JSON between prepare and probe completion; keep keys as strings.
    state['units'] = {str(k): v for k, v in state['units'].items() if k is not None}
    state['notes'] = {str(k): v for k, v in state['notes'].items() if k is not None}
    if not state['jobs']:
        return []
    spec['probe_state'] = state
    return plans


def _radius_options():
    from .native_precheck_questions import RADIUS_OPTIONS
    return RADIUS_OPTIONS


def _centres(points):
    from .person_case_flow import stay_points_from_tracks
    records = [{'fields': {'captureTime': t, 'lon': lon, 'lat': lat, 'deviceName': place}}
               for t, lon, lat, place in points if lon is not None and lat is not None]
    return [(c['lon'], c['lat']) for c in stay_points_from_tracks(records)][:MAX_CENTERS]


def complete(spec, results, context, store, uid, sid, applied):
    """Store probe results; return the next round of plans, or [] once the card is annotated."""
    state = spec.get('probe_state')
    if not isinstance(state, dict) or state.get('version') != VERSION:
        return []
    got = {r.get('id'): r for r in results if isinstance(r, dict)} if isinstance(results, list) else {}
    for job_id, job in state['jobs'].items():
        if job['status'] != 'pending':
            continue
        entry = got.get(job_id) or {}
        data = entry.get('data') if entry.get('status') == 'ok' else None
        job['status'] = 'ok' if isinstance(data, dict) else 'failed'
        job['data'] = data if isinstance(data, dict) else None

    plans = []
    if state['round'] == 1:
        centre_job = next((j for j in state['jobs'].values() if any(p[0] == 'centres' for p in j['purposes'])), None)
        if centre_job and centre_job['status'] == 'ok':
            from .provider_contracts import settings
            try:
                compatible = settings(uid).get('coordinate_compatibility', {}).get('police:police') is True
            except Exception:
                compatible = False
            centres = _centres(centre_job['data'].get('points') or [])
            state['centres'] = centres
            index = next(p[1] for p in centre_job['purposes'] if p[0] == 'centres')
            radii = [v for l, v in (spec.get('values') or {}).items() if l in _labels(spec, index) and isinstance(v, int)]
            if compatible and centres and radii:
                state['round'] = 2

                def build(kind, scope):
                    return _freeze(store, uid, sid, applied, kind, context, scope['start'], scope['end'],
                                   scope['radius'], None, scope['point'])
                for point in centres:
                    _job(state, plans, build, 'incidents', [['around', index]], start=centre_job['window'][0],
                         end=centre_job['window'][1], radius=max(radii), point=list(point))
            elif not centres:
                state['empty_centres'] = True
        if plans:
            return plans
    annotate_counts(spec, state)
    return []


def _count_times(items, position, window):
    left, right = window
    return sum(1 for item in items if isinstance(item[position], str) and left <= item[position] <= right)


def annotate_counts(spec, state):
    from .native_precheck_questions import annotate
    values = spec.get('values') or {}
    counts = {}
    for job in state['jobs'].values():
        data = job.get('data') if job['status'] == 'ok' else None
        for purpose in job['purposes']:
            kind, index = purpose[0], purpose[1]
            bucket = counts.setdefault(index, {})
            if kind == 'option':
                bucket[purpose[2]] = data['total'] if data and type(data.get('total')) is int else None
            elif kind == 'time':
                items, position = ((data or {}).get('points'), 0) if job['kind'] == 'tracks' else ((data or {}).get('rows'), 1)
                for label, window in _windows(spec, index).items():
                    bucket[label] = _count_times(items, position, window) if items is not None else None
            elif kind == 'radius':
                rows, origin = (data or {}).get('rows'), job.get('origin')
                for label in _labels(spec, index):
                    if not isinstance(values[label], int):
                        continue
                    bucket[label] = None if rows is None or origin is None else sum(
                        1 for _, _, lon, lat in rows
                        if (_distance(origin[0], origin[1], lon, lat) or math.inf) <= values[label])
            elif kind == 'centres' and state['round'] != 2:
                for label in _labels(spec, index):
                    if isinstance(values[label], int):
                        bucket[label] = 0 if data and state.get('empty_centres') else None
    around = [j for j in state['jobs'].values() if any(p[0] == 'around' for p in j['purposes'])]
    if around:
        index = next(p[1] for p in around[0]['purposes'] if p[0] == 'around')
        done = [j for j in around if j['status'] == 'ok']
        bucket = counts.setdefault(index, {})
        for label in _labels(spec, index):
            radius = values[label]
            if not isinstance(radius, int):
                continue
            if not done:
                bucket[label] = None
                continue
            hits = set()
            for job in done:
                for number, _, lon, lat in job['data'].get('rows') or []:
                    if (_distance(job['point'][0], job['point'][1], lon, lat) or math.inf) <= radius:
                        hits.add(number)
            bucket[label] = len(hits)
    counts = {k: v for k, v in counts.items() if v and k is not None}
    state['empty'] = all_empty(spec, counts)
    annotate(spec, counts, {int(k): v for k, v in state['units'].items()},
             {int(k): v for k, v in (state.get('notes') or {}).items()})
    state['counts'] = {str(k): v for k, v in counts.items()}
    for job in state['jobs'].values():
        job.pop('data', None)
    state['round'] = 'done'
    return counts


def all_empty(spec, counts):
    """Every option of every question was probed successfully and found nothing."""
    questions = spec.get('questions') or []
    base = spec.get('base_labels') or {}
    return bool(questions) and all(
        question.get('options') and all(counts.get(index, {}).get(base.get(o['label'], o['label']), None) == 0
                                        for o in question['options'])
        for index, question in enumerate(questions))


def empty_summary(spec):
    labels = [(spec.get('base_labels') or {}).get(o['label'], o['label'])
              for q in spec.get('questions') or [] for o in q.get('options') or []]
    return '、'.join(labels) + '均无记录' if labels else '各可选范围均无记录'


def audit(spec):
    """Counts-only record for the Run snapshot."""
    state = spec.get('probe_state') or {}
    return {'version': VERSION, 'kind': spec.get('kind'), 'code': spec.get('code'),
            'jobs': [{'kind': j['kind'], 'window': j['window'], 'radius': j['radius'], 'status': j['status']}
                     for j in state.get('jobs', {}).values()],
            'counts': copy.deepcopy(state.get('counts') or {}), 'empty': state.get('empty') is True}
