"""Conservative rule coverage, never semantic certification of arbitrary prose."""
import re
VERSION='narrative-review-v2'
SAFE=('以下为辅助说明。','请查看来源记录和资料缺口。','可展开来源查看原始记录。','缺失资料不能视为零条或没有发生。','同框不能推导为同行。','资金往来不能认定为赌资。')


def review(text,claims,usage=None):
    if not text:return {'status':'not_generated','text':None,'claim_refs':[],'conflicts':[],'review_version':VERSION,'coverage':'固定句式与受保护字段检查'}
    if not isinstance(text,str) or len(text)>60000:return {'status':'unverified','text':None,'claim_refs':[],'conflicts':[],'review_version':VERSION,'coverage':'说明超出检查预算'}
    remainder=text;refs=[]
    for claim in sorted(claims,key=lambda x:len(x['statement']),reverse=True):
        if claim['statement'] in remainder:refs.append(claim['claim_id']);remainder=remainder.replace(claim['statement'],'')
    for phrase in SAFE:remainder=remainder.replace(phrase,'')
    conflicts=[]
    history='本次使用历史可信结果，未重新查询。'
    if history in remainder:
        if (usage or {}).get('status')=='historical_evidence':remainder=remainder.replace(history,'')
        else:conflicts.append({'code':'data_usage_conflict','message':'说明中的历史复用与本轮真实查询状态不一致。'})
    if re.search(r'实施(?:了)?盗窃|就是(?:小偷|赌徒)|(?:认定|确认为|属于|是)赌资|嫌疑(?:排名|等级)|风险(?:分数|评分)|犯罪(?:倾向|概率)|同框.{0,8}(?:证明|说明).{0,8}同行|(?:unknown|未知|缺失).{0,8}(?:为|是|等于)\s*0|(?:没有|不存在)(?:同行|关系|交易)',remainder):conflicts.append({'code':'unsupported_conclusion','message':'包含无依据定性或将未知写成否定事实。'})
    # Any unbound number, time, source identifier or factual relation is withheld.
    if re.search(r'\d|DEMO-|同乘|独行|同行|同框|转账|金额|账户|车辆|人员|对象',remainder):conflicts.append({'code':'unbound_protected_fields','message':'受保护字段未与固定Claim句式绑定。'})
    remaining=re.sub(r'[\s#*•—，。；：、!?！？,.()（）-]+','',remainder)
    return {'status':'conflicted' if conflicts else 'unverified' if remaining else 'verified','text':text,'claim_refs':sorted(set(refs)),'conflicts':conflicts,'review_version':VERSION,'coverage':'仅完整匹配固定Claim或白名单说明才通过；其余文字未作语义核验'}
