"""Finite presentation clauses; unknown targets/ranges remain fail-closed.

This only reads the user's request. File contents, tool results and model prose
are never inputs. Do not remove arbitrary text after '附件' or '说明'.
"""
import re
import unicodedata

VERSION = 'request-language-v1'
PRESENTATION = (
    r'(?:请)?(?:使用)?(?:资金往来整理|夜间活动整理|同行与共现核对|已有关系核对|车辆资料整理)方法(?:并完成摘要核对)?',
    r'(?:请)?(?:并)?完成摘要核对',
    r'(?:请)?只依据已取得的(?:合成)?资料(?:说明|展示|列出)(?:记录数|时间|收支方向|来源编号)(?:[、与和](?:记录数|时间|收支方向|来源编号))*',
    r'附件仅(?:为|用于)(?:页面|界面|上传|功能)?测试',
    r'(?:附件)?(?:不能|不要)(?:将附件)?作为资料来源',
    r'(?:请)?(?:用中文回答|使用简体中文回答|按时间顺序展示|按时间顺序列出|保留来源编号)',
)


def normalize(text):
    value = unicodedata.normalize('NFKC', text).strip()
    parts = re.split(r'[，,。；;\n]', value)
    # A method declaration is redundant only when it agrees with the main clause.
    # Keep conflicting declarations visible to the router's normal rejection.
    methods={'资金往来整理':'资金','夜间活动整理':'夜间','同行与共现核对':'同行','已有关系核对':'关系','车辆资料整理':'车辆'}
    patterns=list(PRESENTATION)
    if any(name in value and keyword not in parts[0] for name,keyword in methods.items()):
        patterns=patterns[1:]
    value = '，'.join(part.strip() for part in parts if part.strip() and not any(
        re.fullmatch(pattern, part.strip()) for pattern in patterns))
    value = re.sub(r'当前(?=涉赌|盗窃)', '', value)
    value = re.sub(r'^(?:能否|可以|麻烦)(?:请)?(?:帮我)?', '请', value)
    return value
