"""Deterministic task candidates. Text never grants a capability."""
import re
import unicodedata

VERSION = 'peixian-router-v1'
WORDS = {
    'night_activity': ('夜间', '夜晚', '晚上', '夜里'),
    'companions_check': ('同行', '同框', '共现', '共同出现', '一起出现'),
    'funds_analysis': ('资金', '流水', '转账', '收支'),
    'relations_check': ('已有关系', '之间的关系', '有没有关系', '关联互查', '关系资料'),
}
METHODS = {'night_activity': ['night'], 'companions_check': ['companions'],
           'funds_analysis': ['funds'], 'relations_check': ['relations']}


def parse(text, selected=False):
    text = unicodedata.normalize('NFKC', text).strip()
    # Quoted documents/code are not routing directives. Unresolved text is clarified.
    clean = re.sub(r'```.*?```|“[^”]*”|"[^\"]*"', '', text, flags=re.S)
    no = re.findall(r'(?:不要|不用|不必|别|无需|不)(?:再|重新)?(?:查询|取数|查|取)', clean)
    positive = clean
    for term in no:
        positive = positive.replace(term, '')
    refresh = re.findall(r'重新(?:查询|查|核对)|再取一次|更新(?:一下|资料|结果)?|(?:查询|查|取).*?最新', positive)
    history = re.findall(r'上一条|刚才|之前的?(?:数据|结果)|继续(?:说|解释)?|展开说明|解释.*?结果|只(?:解释|说明)', clean)
    intents = [intent for intent, words in WORDS.items() if any(word in clean for word in words)]
    integrated = bool(re.search(r'综合(?:看|整理|分析)|全面整理|总流程', clean))
    concept = bool(re.search(r'是什么(?:意思)?|什么是|什么意思|有什么区别|为什么缺失不能当作零|如何使用|怎么使用', clean))
    unsupported = bool(re.search(r'身份证|\d{17}[\dXx]|DEMO-|(?:最近|过去|近)\s*[\d一二三四五六七八九十]+[天周月年]|20\d\d[-/年]\d', clean))
    injection = bool(re.search(r'忽略.*?(?:限制|规则|权限)|全部插件|所有插件|直接调用.*?插件|不要.*?权限校验|allowed_tools|task_spec', clean))
    conflict = ['query_mode'] if no and refresh else []
    related = bool(intents or integrated or no or refresh or history or unsupported or injection
                   or re.search(r'分析|查询|核对|看看|查一下|整理|统计|列出|展示', clean))
    mode, intent = 'new_query', None
    greeting=bool(re.fullmatch(r'(?:你好|您好|谢谢|再见|早上好|晚上好)[！!。，,.？?]*',clean))
    if greeting:
        related,mode,intent=False,None,None
    elif concept and not (refresh or no or re.search(r'刚才|上一条', clean)):
        related, mode, intent = False, None, None
    elif conflict or unsupported or injection:
        mode, intent = 'clarify', 'clarification'
    elif no or (history and not refresh):
        mode, intent = 'explain_existing', 'explain_result'
    elif integrated:
        intent = 'integrated_analysis'
    elif len(intents) == 1:
        intent = intents[0]
    elif len(intents) > 1:
        mode, intent, conflict = 'clarify', 'clarification', ['intent']
    elif related and not selected:
        mode, intent = 'clarify', 'clarification'
    if not related:mode,intent=None,None
    return {'schema_version': 'task-candidate-v1', 'router_version': VERSION,
            'data_related': related, 'query_mode_candidate': mode, 'intent_candidate': intent,
            'target_mentions': [], 'history_terms': history, 'refresh_terms': refresh,
            'no_refresh_terms': no, 'matched_patterns': intents, 'conflicts': conflict,
            'unsupported_scope': unsupported, 'untrusted_directive': injection}
