"""Native theft-tool conditions. Facts are accepted only from user-confirmed scope.

This module has no business workflow graph. It records exact input values and
rejects model-generated widening. A model chooses the next tool and can ask a
question; only the independent execution gate may call a supplier.
"""
import copy
import re
import uuid
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from .backend_contract import error
from .data_plugin_policy import ACTIVE_KINDS
from .theft_planner import slots
from shared import theft_provider_v2 as adapter

TOOL_TO_KIND={'peixian_query_'+kind:kind for kind in ACTIVE_KINDS}
SCORING_REQUEST=re.compile(r'评分|打分|可疑度|嫌疑评估|研判优先级|嫌疑程度|排序|筛选嫌疑人|可能性|嫌疑人列表|核验前')
SCORING_NEGATE=re.compile(
    r'不要\s*(?:评分|排序|研判)|无需\s*(?:评分|排序)|不用\s*(?:评分|排序|打分)|'
    r'不\s*要\s*打分|禁止\s*(?:评分|排序)|取消\s*(?:评分|排序)'
)
CASE_HINT=re.compile(r'案件|警情|案发|盗窃案|由案到人|周边人员|可疑人员')
PERSON_HINT=re.compile(r'由人到案|此人|该人|这名人员|已确认人员')
ADDRESS=re.compile(r'[\u4e00-\u9fa5A-Za-z0-9·]{2,20}?(?:小区|花园|家园|家属院|名邸|公寓|新村|苑|广场|大厦|商圈|御景|公园|玫瑰园|碧桂园)')
PLACE=re.compile(r'[\u4e00-\u9fa5A-Za-z0-9·]{1,20}?(?:路|街|巷|大道|村|镇|市场|超市|商场|学校|中学|小学|医院|车站|酒店|宾馆|菜场)(?:\d{1,5}号(?:楼)?)?')
NEARBY=re.compile(r'([\u4e00-\u9fa5A-Za-z0-9·]{2,20}?)(?:附近|周边|一带)')
ADDRESS_PREFIX=re.compile(r'^(?:由案到人)?(?:请|帮我|帮忙|麻烦)?(?:查一下|查询一下|查询|查查|查|看看|看一下|分析一下|分析|核查一下|核查|研判一下|研判|排查一下|排查)?(?:在|位于)?')
CASE_INTENT=re.compile(r'附近|周边|一带|可疑|警情|案|盗|抢|扒窃')
NOT_ADDRESS=re.compile(r'查|看|分析|对比|重新|再|跨|这些|哪|他|她|平时|同期|夜间|轨迹|人员|身份证|此人|该人|这个人|最近|近\d')
VAGUE_ADDRESS={'附近','周边','这里','那里','案发地','该地','本地','此地','这个地方','那个地方','沛县'}
CASE_TYPES=(
    ('入室盗窃',('入室盗窃','入户盗窃')),
    ('盗窃电动车',('盗窃电动车','电动车盗窃','电动车被盗','偷电动车','盗窃电瓶车','电瓶车被盗')),
    ('盗窃车内财物',('盗窃车内财物','车内财物被盗','砸车窗')),
    ('商铺盗窃',('商铺盗窃','店铺盗窃')),
    ('扒窃',('扒窃','扒手')),
    ('抢劫',('抢劫',)),
    ('抢夺',('抢夺',)),
)
PHONE=re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)')
NAMED=re.compile(r'(?:姓名|名字|名叫)[是为叫:：\s]*([\u4e00-\u9fa5·]{2,4}?)(?=$|[^\u4e00-\u9fa5·]|的|这|此)')
LOOKUP_NAME=re.compile(r'(?:查一下|查询一下|查查|查询|核查一下|核查|查)([\u4e00-\u9fa5·]{2,4}?)(?:这个人|这名人员|此人|的情况|的轨迹|的活动|的预警|的档案|有没有|是否)')
NOT_NAME=re.compile(r'他|她|此|该|这|那|谁|什么|人员|嫌疑|附近|周边|小区|警情|案件|轨迹|身份|手机|一下|情况|最近')
CN_NUMBER={'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}


NUMBER=re.compile(r'-?\d+(?:\.\d+)?')


def grounded_arguments(kind, args, context):
    """Treat model-filled placeholders as missing so the platform card asks instead.

    The plugin schemas make models fill lon/lat/start/end even when the user gave
    none (0, "", 2000-01-01). Coordinates and times survive only when the user or
    a card answer stated them.
    """
    if not isinstance(args,dict):
        return args
    kept={k:v for k,v in args.items() if v is not None and not (isinstance(v,str) and not v.strip())}
    text=(context.get('constraints_text') or '')+' '+(context.get('current_text') or '')
    if kind=='incidents' and {'lon','lat'}&kept.keys():
        said={Decimal(n) for n in NUMBER.findall(text)}
        def stated(value):
            # Zero is always a placeholder; "00" in a time like 15:20:00 must not ground it.
            try:number=Decimal(str(value).strip());return number!=0 and number in said
            except (InvalidOperation,ValueError):return False
        if not all(stated(kept[k]) for k in ('lon','lat') if k in kept):
            kept={k:v for k,v in kept.items() if k not in ('lon','lat')}
    if 'radius_m' in kept:
        try:
            if Decimal(str(kept['radius_m']).strip())<=0:kept.pop('radius_m')
        except (InvalidOperation,ValueError):pass
    if {'start','end'}&kept.keys():
        known=[context.get('confirmed') or {},context.get('capture_conditions') or {}]
        def stated_time(key):
            value=str(kept.get(key) or '').strip()
            return bool(value) and (value[:10] in text or any(str(c.get(key) or '')==value for c in known))
        if not all(stated_time(k) for k in ('start','end') if k in kept):
            kept={k:v for k,v in kept.items() if k not in ('start','end')}
    return kept


def _address_value(raw):
    value = ADDRESS_PREFIX.sub('', raw)
    if len(value) < 2 or value in VAGUE_ADDRESS or NOT_ADDRESS.search(value):
        return None
    return value[:40]


def case_address(text):
    """Address keyword for the /jq/search address match; never coordinates.

    Community names always count. Roads, villages and places count only when the
    text is about a case or is little more than the place itself, so person
    follow-ups that mention a road do not switch direction.
    """
    text = text or ''
    for match in ADDRESS.finditer(text):
        value = _address_value(match.group(0))
        if value:
            return value
    short = lambda value: len(re.sub(r'\s', '', text)) - len(value) <= 6
    for match in PLACE.finditer(text):
        value = _address_value(match.group(0))
        if value and (CASE_INTENT.search(text) or short(value)):
            return value
    for match in NEARBY.finditer(text):
        value = _address_value(match.group(1))
        if value:
            return value
    return None


community_address = case_address


def person_lookup(text):
    """A person given only by phone number or by an explicitly written name."""
    text=text or ''
    if re.search(r'(?<!\d)\d{17}[\dXx](?!\d)',text):
        return {}
    phone=PHONE.search(text)
    if phone:
        return {'person_phone':phone.group()}
    for pattern in (NAMED,LOOKUP_NAME):
        found=pattern.search(text)
        if found and not NOT_NAME.search(found.group(1)):
            return {'person_name':found.group(1)}
    return {}


def case_type(text):
    """Supplier ajType keyword named by the user; bare '盗窃' is the default scope already."""
    for name, words in CASE_TYPES:
        if any(w in (text or '') for w in words):
            return name
    return None


def relative_window(text, now=None):
    """Start/end for relative phrases; None when absent or longer than one query may span."""
    text = text or ''
    now = (now or datetime.now()).replace(microsecond=0)
    day = lambda d: d.replace(hour=0, minute=0, second=0)
    fmt = lambda d: d.strftime('%Y-%m-%d %H:%M:%S')
    last = lambda d: d.replace(hour=23, minute=59, second=59)
    match = re.search(r'(?:最近|近|过去)\s*(\d{1,3}|[一二两三四五六七八九十]{1,3})\s*(?:天|日)', text)
    days = None
    if match:
        raw = match.group(1)
        if raw.isdigit():
            days = int(raw)
        elif '十' in raw:
            tens, _, ones = raw.partition('十')
            days = CN_NUMBER.get(tens, 1 if not tens else 0) * 10 + CN_NUMBER.get(ones, 0)
        else:
            days = CN_NUMBER.get(raw[-1], 0)
    elif re.search(r'(?:最近|近)\s*一?\s*(?:周|星期)', text):
        days = 7
    elif re.search(r'(?:最近|近)\s*半\s*个?月', text):
        days = 15
    elif re.search(r'(?:最近|近)\s*一?\s*个?月', text):
        days = 30
    if days:
        if days > MAX_QUERY_DAYS:
            return None
        return {'start': fmt(now - timedelta(days=days)), 'end': fmt(now)}
    if '前天' in text:
        d = now - timedelta(days=2)
        return {'start': fmt(day(d)), 'end': fmt(last(d))}
    if '昨天' in text or '昨晚' in text:
        d = now - timedelta(days=1)
        return {'start': fmt(day(d)), 'end': fmt(last(d))}
    if '今天' in text:
        return {'start': fmt(day(now)), 'end': fmt(now)}
    monday = day(now - timedelta(days=now.weekday()))
    if '上周' in text:
        return {'start': fmt(monday - timedelta(days=7)), 'end': fmt(monday - timedelta(seconds=1))}
    if '本周' in text or '这周' in text:
        return {'start': fmt(monday), 'end': fmt(now)}
    match = re.search(r'(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]', text)
    if match and not re.search(r'\d{1,2}\s*月\s*\d{1,2}\s*[日号]\s*(?:至|到|-|—)', text):
        try:
            d = now.replace(month=int(match.group(1)), day=int(match.group(2)), hour=0, minute=0, second=0)
        except ValueError:
            return None
        if d > now:
            d = d.replace(year=d.year - 1)
        return {'start': fmt(d), 'end': fmt(last(d))}
    return None


def scoring_requested(text, prior=None, direction=None):
    """Freeze scoring intent. case_to_person and person_to_case default on unless negated."""
    if not isinstance(text, str):
        if prior and 'scoring_requested' in prior:
            return bool(prior.get('scoring_requested'))
        return direction in ('case_to_person', 'person_to_case')
    if SCORING_NEGATE.search(text):
        return False
    if SCORING_REQUEST.search(text):
        return True
    if prior and 'scoring_requested' in prior:
        return bool(prior.get('scoring_requested'))
    return direction in ('case_to_person', 'person_to_case')



def infer_direction(confirmed, refs, text, prior=None):
    """Implicit case_to_person / person_to_case; user never picks a mode."""
    if {'person_identity','person_name','person_phone'} & set(confirmed or {}) or PERSON_HINT.search(text or ''):
        return 'person_to_case'
    if refs:
        # Selected sources may already bind a person; prefer person_to_case when prior said so.
        if prior and prior.get('direction') == 'person_to_case' and 'person_identity' in (prior.get('confirmed') or {}):
            return 'person_to_case'
    if ({'lon', 'lat'} <= set((confirmed or {}).keys()) or (confirmed or {}).get('case_type')
            or CASE_HINT.search(text or '') or case_address(text) or case_type(text)):
        return 'case_to_person'
    if prior and prior.get('direction') in ('case_to_person', 'person_to_case'):
        return prior['direction']
    return 'unknown'


def freeze_context(store,uid,sid,data):
    """Freeze explicit user conditions with a stable session task identity."""
    text=data['text']
    parsed=slots(text,data.get('scope'))
    current={v['field']:v['value'] for v in parsed.values()}
    lookup={} if {'person_identity','lon','lat'}&current.keys() else person_lookup(text)
    entry={} if {'person_identity','lon','lat'}&current.keys() or lookup else {'address':case_address(text),'case_type':case_type(text)}
    entry={k:v for k,v in entry.items() if v}
    current.update(entry)
    current.update(lookup)
    incident_window=None
    if entry:
        incident_window={k:current[k] for k in ('start','end')} if {'start','end'}<=current.keys() else relative_window(text)
    prior=None
    for row in store.rows("SELECT request_ciphertext FROM business_runs WHERE uid=? AND session_id=? ORDER BY rowid DESC LIMIT 30",(uid,sid)):
        snapshot=store.decrypt(row['request_ciphertext'])
        if snapshot.get('native_tool_context'):
            prior=snapshot['native_tool_context']
            break
    task_id=prior['task_id'] if prior else uuid.uuid4().hex
    confirmed=copy.deepcopy(prior['confirmed']) if prior else {}
    confirmed.update(current)
    # A user can change direction within one task. When the new object is only
    # described as 'another' one, never reuse the former person's identity or
    # position merely because it was confirmed in an earlier Run.
    ambiguous_person=bool(re.search(r'另一个人|其他人员|换个人|换一名人员|另一个对象',text) and 'person_identity' not in current)
    ambiguous_location=bool(re.search(r'另一个位置|其他地点|换个地点|另一个警情',text) and not {'lon','lat'}<=current.keys())
    if ambiguous_person:confirmed.pop('person_identity',None)
    if ambiguous_location:confirmed.pop('lon',None);confirmed.pop('lat',None)
    # A new explicit object or position supersedes any earlier selected source.
    # Otherwise a later question could silently query the old source instead.
    changed_object=any(canonical_field(k, current[k]) != canonical_field(k, (prior or {}).get('confirmed', {}).get(k)) if (prior or {}).get('confirmed', {}).get(k) is not None else True for k in ('person_identity','lon','lat','address','case_type','person_name','person_phone') if k in current) or ambiguous_person or ambiguous_location
    if changed_object and not entry and {'person_identity','lon','lat'}&current.keys():
        confirmed.pop('address',None);confirmed.pop('case_type',None)
    if (entry or {'person_identity','lon','lat'}&current.keys()) and not lookup:
        confirmed.pop('person_name',None);confirmed.pop('person_phone',None)
    if lookup and changed_object:
        # A person named by phone or name replaces every earlier object.
        for key in ('person_identity','lon','lat','address','case_type','person_name','person_phone'):
            if key not in lookup:confirmed.pop(key,None)
    if entry and 'person_identity' not in current:
        confirmed.pop('person_identity',None);confirmed.pop('lon',None);confirmed.pop('lat',None)
        # A new case entry replaces the former one as a whole.
        for key in ('address','case_type'):
            if key not in entry:confirmed.pop(key,None)
    if 'source_refs' in data:
        refs=copy.deepcopy(data['source_refs'])
    else:
        named=named_sources(store,uid,sid,text)
        refs=named if named else ([] if changed_object else copy.deepcopy(prior.get('source_refs',[]) if prior else []))
        if '来源记录编号' in text and not named:
            error('source_record_unavailable','所述来源编号未在本人本会话结果中找到。',409)
    if not isinstance(refs,list) or len(refs)>20:
        error('source_selection_invalid','请选择明确的来源记录，不自动选择候选。',422)
    if refs:
        from .analysis_tasks import source
        for ref in refs:source(store,uid,sid,ref,'acceptance_real')
    prior_constraints=prior.get('constraints_text','') if prior else ''
    if re.search(r'同意使用上游默认覆盖范围',text):
        prior_constraints=''
    constraints=(prior_constraints+' '+text)[-12000:]
    direction=infer_direction(confirmed, refs, text, prior)
    stop_phrase='不再追问，请基于已取得资料直接作答。'
    stop_followup=bool((prior or {}).get('stop_followup')) or (text.strip() == stop_phrase) or ('不再追问' in text and '直接作答' in text)
    capture_conditions={} if changed_object else copy.deepcopy((prior or {}).get('capture_conditions',{}))
    explicit_capture_position=False
    if re.search(r'抓拍',text):
        capture_conditions.update({k:current[k] for k in ('start','end','radius_m') if k in current})
        explicit_capture_position={'lon','lat'}<=current.keys() and not refs
    return {'version':'native-tool-context-v1','task_id':task_id,
        'scope_version':prior['scope_version']+1 if prior else 1,
        'confirmed':confirmed,'source_refs':refs,
        'query_rules_version':'on-demand-v1',
        'capture_scope_version':'capture-purpose-v1',
        'source_selection':'explicit',
        'capture_conditions':capture_conditions,
        'capture_position_confirmed':explicit_capture_position or (bool((prior or {}).get('capture_position_confirmed')) and not changed_object),
        'current_text':text,'constraints_text':constraints,'user_conditions':current,
        'scoring_requested':scoring_requested(text,prior,direction),
        'direction':direction,
        'candidate_request_n':None,
        'candidate_set':[],
        'enrichment_plan':None,
        'person_case_plan':None,
        'center_set':[],
        'case_info':None if changed_object else copy.deepcopy((prior or {}).get('case_info')),
        'incident_window':incident_window or (None if changed_object else copy.deepcopy((prior or {}).get('incident_window'))),
        'stop_followup':stop_followup}


FIELD_NAMES = {'person_identity':'人员','person_name':'姓名','person_phone':'手机号','start':'开始时间','end':'结束时间','lon':'经度','lat':'纬度','radius_m':'半径','page':'页码','page_size':'每页条数'}


def canonical_field(key, value):
    """Only representation equivalence; never infer dates, timezone or units."""
    try:
        if key in ('page','page_size'):
            if type(value) is int: return value
            if isinstance(value,str) and re.fullmatch(r'[0-9]{1,9}',value): return int(value)
            raise ValueError()
        if key in ('start','end'):
            if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}',value): raise ValueError()
            return datetime.strptime(value.replace('T',' '),'%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d %H:%M:%S')
        if key in ('lon','lat','radius_m'):
            if isinstance(value,bool) or not isinstance(value,(str,int,float)): raise ValueError()
            n=Decimal(str(value))
            if not n.is_finite(): raise ValueError()
            return format(n.normalize(),'f')
        return value
    except (ValueError,InvalidOperation,OverflowError):
        error('scope_parameter_invalid','参数格式无效，尚未查询；请仅补充提示字段。',422,{key:FIELD_NAMES.get(key,key)+'格式不符合接口合同'})


MAX_QUERY_DAYS=31


def time_window_span(start, end):
    try:
        left,right=(datetime.strptime(str(v).replace('T',' '),'%Y-%m-%d %H:%M:%S') for v in (start,end))
    except ValueError:
        return None
    return right-left


def check_time_window(start, end):
    span=time_window_span(start,end)
    if span is None:
        return
    if span.total_seconds()<=0 or span.total_seconds()>MAX_QUERY_DAYS*86400:
        from fastapi import HTTPException
        raise HTTPException(409,{'code':'time_range_limit',
            'message':f'开始时间须早于结束时间，且单次时间跨度不超过 {MAX_QUERY_DAYS} 天；尚未访问资料接口。',
            'field_errors':{'start':'超出接口限制','end':'超出接口限制'},'limits':{'max_days':MAX_QUERY_DAYS}})


def resolve_arguments(kind, args, context):
    if not isinstance(args,dict): error('native_tool_invalid','资料工具参数必须是对象。',422)
    resolved=copy.deepcopy(args)
    confirmed=context.get('capture_conditions',{}) if kind=='captures' and (context.get('capture_scope_version')=='capture-purpose-v1' or context.get('dialogue_policy')=='adaptive-dialogue-v1') else context['confirmed']
    # Only fill existing task-bound conditions, never new objects or inferred times.
    reusable=set()
    if kind in adapter.PERSON and not context['source_refs']: reusable.add('person_identity')
    if kind in adapter.TIMED and kind!='captures': reusable.update(('start','end'))
    if kind=='captures': reusable.update({'start','end','radius_m'})
    if kind=='warnings' and not {'person_name','person_phone'}&resolved.keys():
        reusable.update(('person_name','person_phone'))
    for key in reusable:
        if key not in resolved and key in confirmed: resolved[key]=copy.deepcopy(confirmed[key])
    if kind=='incidents':
        if context.get('direction')=='person_to_case' and {'start','end'}<=confirmed.keys():
            for key in ('start','end'):resolved.setdefault(key,copy.deepcopy(confirmed[key]))
        if context.get('direction')=='person_to_case' and context['source_refs'] and 'radius_m' in confirmed:
            resolved.setdefault('radius_m',copy.deepcopy(confirmed['radius_m']))
        if (context.get('direction')=='case_to_person' and not context['source_refs']
                and not {'lon','lat'}&resolved.keys() and (confirmed.get('address') or confirmed.get('case_type'))):
            for key in ('address','case_type'):
                if confirmed.get(key):resolved[key]=confirmed[key]
            resolved.pop('radius_m',None)
            # Card answers for captures also land in confirmed; only the incident window applies here.
            resolved.pop('start',None);resolved.pop('end',None)
            resolved.update(context.get('incident_window') or {})
    return {key:canonical_field(key,value) for key,value in resolved.items()}


def arguments(kind,args,context):
    """Accept model-supplied values with format and required-field checks only.

    Authorization-style blocks (scope_unconfirmed, capture_scope_unconfirmed,
    page_unconfirmed, unsupported_scope) are removed. Values that pass
    canonical_field are accepted and may be written back to confirmed by the caller.
    """
    if kind not in ACTIVE_KINDS or not isinstance(args,dict):
        error('native_tool_invalid','资料工具或参数无效。',422)
    supported={'lon','lat','radius_m','person_identity','start','end','page','page_size'}
    if kind=='captures':supported-={'lon','lat'}
    if kind=='incidents':supported|={'address','case_type'}
    if kind=='warnings':supported={'person_name','person_phone','page','page_size'}
    if set(args)-supported:
        error('native_tool_invalid','查询参数包含未开放的条件。',422)
    args=resolve_arguments(kind,args,context)
    if kind=='warnings':
        return lookup_arguments(args,context)
    if kind=='captures' and (context.get('capture_scope_version')=='capture-purpose-v1' or context.get('dialogue_policy')=='adaptive-dialogue-v1'):
        conditions=context.get('capture_conditions',{})
        absent={k:FIELD_NAMES[k]+'需针对抓拍查询明确' for k in ('start','end','radius_m') if k not in conditions or (k in args and canonical_field(k,args[k])!=canonical_field(k,conditions[k]))}
        if absent:error('scope_missing','请补充抓拍查询的指定条件。',409,absent)
    if isinstance(args.get('person_identity'),str) and args['person_identity'].startswith('person-'):
        error('identity_parameter_invalid','person_identity 必须使用已确认的原始身份号码，不能使用展示引用。',409)
    if context['source_refs'] and {'lon','lat','person_identity'} & args.keys():
        error('source_value_override','已选择来源时不能再替换对象或坐标。',409)
    required=({'radius_m'} if context['source_refs'] else {'lon','lat','radius_m'}) if kind=='incidents' else {'radius_m'} if kind=='captures' else set() if context['source_refs'] else {'person_identity'}
    if kind=='incidents' and args.get('address') and not context['source_refs']:required=set()
    elif kind=='incidents' and args.get('case_type') and not context['source_refs']:required={'start','end'}
    if kind in adapter.TIMED:required|={'start','end'}
    if not required<=set(args):
        error('scope_missing','查询条件不完整，未访问资料接口；只补充列出的字段，不重试或猜测权限。',409,{k:FIELD_NAMES[k]+'尚未明确' for k in sorted(required-set(args))})
    if kind=='captures' and len(context['source_refs'])!=1 and not (context.get('capture_position_confirmed') and {'lon','lat'} <= context.get('confirmed',{}).keys()):
        error('source_selection_required','周边抓拍必须先选择一个明确的位置来源。',409)
    if kind in adapter.TIMED or (kind=='incidents' and {'start','end'}<=args.keys()):
        check_time_window(args['start'],args['end'])
    # Accept model values into confirmed so later turns see them as known.
    confirmed=context.setdefault('confirmed',{})
    user_conditions=context.setdefault('user_conditions',{})
    for key,value in args.items():
        if key=='person_identity':
            continue
        confirmed[key]=copy.deepcopy(value)
        user_conditions[key]=copy.deepcopy(value)
    applicable=({'lon','lat','radius_m'} if kind in ('incidents','captures') else set())|({'start','end'} if kind in adapter.TIMED else set())|({'page','page_size'} if kind in adapter.PAGED else set())
    if kind=='incidents':
        applicable|={'start','end'} if {'start','end'}<=args.keys() else set()
        if not context['source_refs']:applicable|={k for k in ('address','case_type') if args.get(k)}
    query={key:copy.deepcopy(value) for key,value in args.items() if key in applicable}
    if kind=='captures' and not context['source_refs'] and context.get('capture_position_confirmed'):
        query.update({k:canonical_field(k,context['confirmed'][k]) for k in ('lon','lat')})
    return query

def lookup_arguments(args,context):
    """Only the name or phone the user wrote may be searched; one key per call."""
    keys=[k for k in ('person_name','person_phone') if args.get(k)]
    if not keys:
        error('person_lookup_invalid','缺少人员姓名或手机号。',409)
    if len(keys)>1:
        error('native_tool_invalid','姓名和手机号一次只能按一项查找。',422)
    key=keys[0];value=str(args[key]).strip()
    if value!=(context.get('confirmed') or {}).get(key):
        error('person_lookup_invalid','只能按用户提供的姓名或手机号查找。',409)
    query={key:value}
    query.update({k:args[k] for k in ('page','page_size') if k in args})
    return query


def source_values(store,uid,sid,kind,context):
    """Derive one coordinate/person from the exact selected prior source."""
    from .analysis_tasks import source
    if len(context['source_refs'])!=1:
        error('explicit_source_required','请从候选结果中明确选择一条来源。',409)
    reference=context['source_refs'][0]
    record,snapshot=source(store,uid,sid,reference,'acceptance_real')
    native=snapshot.get('native_tool_policy')
    call_id=record.get('call_id')
    if native:
        plan=snapshot.get('native_calls',{}).get(call_id,{}).get('frozen',{})
        entry=snapshot.get('provider_state',{}).get('modules',{}).get(call_id,{})
        expected=reference['run_id']+':'+call_id+':'
    else:
        plan=snapshot.get('provider_plan',{})
        entry=snapshot.get('provider_state',{}).get('modules',{}).get(plan.get('kind'),{})
        expected=reference['run_id']+':'
    if plan.get('version')!=adapter.VERSION or entry.get('status')!='completed':
        error('source_contract_unsupported','所选来源未取得可核对的真实合同结果。',409)
    raw=entry.get('response',{})
    if raw.get('response_snapshot_id')!=reference['snapshot_id']:
        error('source_version_changed','所选来源快照已变化。',409)
    rows=[r for r in raw.get('records',[]) if expected+r.get('source_ref','')==reference['record_id']]
    if len(rows)!=1:
        error('source_record_unavailable','所选来源原始记录无法核对。',409)
    fields=rows[0].get('fields',{})
    projected=adapter.public_result(fields,store.worker_key.encode(),uid+'/'+sid)
    if projected!=record.get('fields'):
        error('source_integrity_failed','来源展示字段与原始记录不一致。',409)
    origin=plan['kind']
    if kind in ('incidents','captures'):
        names=('gisX','gisY') if origin=='incidents' else ('lon','lat') if origin=='tracks' else None
        if not names or any(fields.get(k) is None for k in names):
            error('source_coordinates_missing','所选来源没有完整、受支持的坐标。',409)
        from .provider_contracts import settings
        compatibility=settings(uid).get('coordinate_compatibility',{})
        key=adapter.CATALOG[origin][3]+':'+adapter.CATALOG[kind][3]
        if compatibility.get(key) is not True:
            error('coordinate_contract_unconfirmed','来源与目标接口的坐标兼容性尚未确认。',409)
        return {'lon':str(fields[names[0]]),'lat':str(fields[names[1]])},{}
    names=[n for n in ('target_id_card','targetIdCard','idCard') if n in fields]
    if len(names)!=1:
        error('source_identity_missing','所选来源不能唯一确定一名人员。',409)
    identity=adapter.person_id(fields[names[0]])
    ref=adapter.person_ref(identity,store.worker_key.encode(),uid+'/'+sid)
    return {'person_ref':ref},{ref:identity}

def named_sources(store,uid,sid,text):
    """An exact user-written record reference may select a prior owned source."""
    from . import trusted_results
    found=[]
    for row in store.rows("SELECT id,status FROM business_runs WHERE uid=? AND session_id=? ORDER BY rowid DESC LIMIT 50",(uid,sid)):
        if row['status'] not in ('completed','failed','cancelled'):
            continue
        result=trusted_results.read(store,uid,sid,row['id'])
        if result.get('data_environment')!='acceptance_real':
            continue
        for record in result.get('records',[]):
            rid=record.get('record_id')
            if not isinstance(rid,str):
                continue
            if re.search(r'(?<![\w:-])'+re.escape(rid)+r'(?![\w:-])',text):
                found.append({'run_id':row['id'],'result_digest':trusted_results.digest(result),
                    'record_id':rid,'snapshot_id':record['snapshot_id']})
    unique={adapter.digest(ref):ref for ref in found}
    if len(unique)>20:
        error('source_selection_limit','本次选定的来源过多，请明确其中一条。',422)
    return list(unique.values())


def model_context(context):
    """Expose confirmed conditions; the model decides the next useful query."""
    payload = {'version':'native-tool-arguments-v1', 'scope_version':context['scope_version'],
        'confirmed':context['confirmed'], 'selected_source_refs':context['source_refs'],
        'direction':context.get('direction') or 'unknown'}
    return """
本轮对话规则：围绕用户当前问题选择必要工具，不要求八项全查，不按固定人员补查计划执行。
已取得资料足够时直接回答；普通问候、解释、表格调整不取数。
沿用同一任务已确认且用途适用的人员、时间和位置；不要反复确认同一条件。
人员不明确时用 question 只问缺项。缺时间、半径或案件时直接调用对应资料工具（缺项不传），平台返回选项卡后按原样用 question 提问，不要自己写要求填写精确时间的问题。
由人到案：周边警情由平台按轨迹停留点自动查询（每次调用一个停留点，最多3个）。由案到人：周边警情由平台按小区名、路名或场所做地址模糊匹配，或按案件类型加时间查询，案件、抓拍时间（案发前N天）和半径由平台选项卡确认。抓拍时间与半径需用途明确，轨迹时间不自动变成抓拍时间。
person_identity 可使用已确认身份或该任务来源中的人员引用；已选来源的坐标由平台读取。
用户只给姓名或手机号时，先调用 peixian_query_warnings（只传 person_name 或 person_phone 之一），按返回的 lookup.next 处理：唯一匹配直接用该人员引用继续，多人匹配用 question 让用户选一人，零条告知用户未查到。
零记录只写查询时段和 0 条；不得自动扩大范围、自动翻页或重试未知调用。单次时间跨度不超过 31 天。
答复不写免责声明或「不等于/不证明/不代表/仅作参考」类句子。
用户取消补充时停止对应查询，基于成功资料给出阶段回答，不把取消解释为全部资料失败。
资料类回答包含人员基本信息、研判摘要、分析依据、下一步研判；来源事实与模型说明区分。
下一步研判默认不提建议；只有存在影响结论的缺口、需要新查询或需用户确认条件时才提，最多两项，不自动执行。资料已足够时写明现有资料可支撑当前结论即可。可以结合资料对人员的活动目的、行为特点和嫌疑作出研判。
由人到案有可疑结论时写明最可疑警情的警情编号和简要警情；平台未给出最可疑警情时写未发现时空关联警情。时间线中区分处警时间与案发时间。
""" + ('用户已要求停止追问，直接整理已有资料。' if context.get('stop_followup') else '') + '\n' + adapter.canonical(payload)
