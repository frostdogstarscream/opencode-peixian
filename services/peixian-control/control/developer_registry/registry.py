"""Release-owned capabilities and fixed implementations. JSON is data, never code."""
import copy
import hashlib
import json
import re
from pathlib import Path
import jsonschema

STATES=['contract_only','adapter_ready','verified','published','disabled','deprecated']
VERSIONS={'capability_registry_version':'capability-registry-v1','rule_registry_version':'rule-registry-v1','method_dependency_version':'method-dependency-v1'}
MODULES=('funds','calls','portrait','composite','night','vehicle','lookup')
METHODS={'night':['night'],'companions':['portrait'],'funds':['funds'],'relations':['lookup','composite'],'vehicles':['vehicle']}
AGENTS={'gambling-assistant':{'night','companions','funds','relations'},'theft-assistant':{'night','companions','vehicles'}}
SEMVER=r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'

def version(value):
    if not isinstance(value,str) or not re.fullmatch(SEMVER,value):raise ValueError('invalid_semver')
    return tuple(map(int,value.split('.')))

def bounds(value):
    if not isinstance(value,str):raise ValueError('invalid_semver_range')
    if value.startswith('='):return ('exact',version(value[1:]))
    match=re.fullmatch(r'>=(\S+) <(\S+)',value)
    if not match:raise ValueError('invalid_semver_range')
    low,high=map(version,match.groups())
    if low>=high:raise ValueError('invalid_semver_range')
    return ('range',low,high)

def compatible(value,expression):
    actual=version(value);limit=bounds(expression)
    return actual==limit[1] if limit[0]=='exact' else limit[1]<=actual<limit[2]

def schema(kind,properties):
    return {'type':'object','additionalProperties':False,'required':list(properties),'properties':properties}

STR={'type':'string','minLength':1}
STRINGS={'type':'array','minItems':1,'uniqueItems':True,'items':STR}
BASE={'schema_version':STR,'id':STR,'version':STR,'state':{'enum':STATES}}
CAP_SCHEMA=schema('capability',{**BASE,'plugin_id':STR,'compatible_versions':STR,'tool_ids':STRINGS,'input_schema':STR,'output_schema':STR,'evidence_schema':STR,'supported_agents':STRINGS,'unavailable_reason':{'type':['string','null']}})
RULE_SCHEMA=schema('rule',{**BASE,'implementation':STR,'input_schema':STR,'output_kind':{'const':'computed'},'supported_agents':STRINGS,'supported_methods':STRINGS})
METHOD_SCHEMA=schema('method',{'agent_id':STR,'method':STR,'required_capabilities':STRINGS,'required_rules':STRINGS})

class Registry:
    def __init__(self,capabilities,rules,methods):
        self._capabilities={};self._rules={};self._methods={}
        for source,target,contract,kind in [(capabilities,self._capabilities,CAP_SCHEMA,'capability'),(rules,self._rules,RULE_SCHEMA,'rule')]:
            for item in source:
                jsonschema.validate(item,contract);version(item['version'])
                if item['schema_version']!=kind+'-registry-v1' or item['id'] in target:raise ValueError('invalid_registry_identity')
                if not set(item['supported_agents'])<=set(AGENTS):raise ValueError('unknown_agent')
                if kind=='capability':
                    module=item['id'].removeprefix('records.')
                    if module not in MODULES or item['id']!='records.'+module or item['plugin_id']!='peixian-records-'+module or item['tool_ids']!=['peixian_get_'+module+'_records']:raise ValueError('invalid_capability_binding')
                    bounds(item['compatible_versions'])
                    if any(item[k]!=module+suffix for k,suffix in [('input_schema','-query-v1'),('output_schema','-records-v1'),('evidence_schema','-evidence-v1')]):raise ValueError('unknown_contract')
                else:
                    ms=item['supported_methods']
                    if len(ms)!=1 or ms[0] not in METHODS or item['implementation']!=ms[0]+'_summary_v1' or item['input_schema']!=ms[0]+'-facts-input-v1':raise ValueError('unknown_implementation')
                    if any(ms[0] not in AGENTS[a] for a in item['supported_agents']):raise ValueError('agent_rule_mismatch')
                    expected=[a.split('-')[0]+'.'+('vehicle' if ms[0]=='vehicles' else ms[0])+'.summary' for a in item['supported_agents']]
                    if expected!=[item['id']]:raise ValueError('invalid_rule_identity')
                target[item['id']]=copy.deepcopy(item)
        for item in methods:
            jsonschema.validate(item,METHOD_SCHEMA)
            key=(item['agent_id'],item['method'])
            if key in self._methods or key[1] not in AGENTS.get(key[0],set()):raise ValueError('invalid_method_binding')
            if item['required_capabilities']!=['records.'+m for m in METHODS[key[1]]]:raise ValueError('method_capability_mismatch')
            for cid in item['required_capabilities']:
                if cid not in self._capabilities or key[0] not in self._capabilities[cid]['supported_agents']:raise ValueError('agent_capability_mismatch')
            if len(item['required_rules'])!=1:raise ValueError('method_rule_mismatch')
            for rid in item['required_rules']:
                rule=self._rules.get(rid,{})
                if key[0] not in rule.get('supported_agents',[]) or key[1] not in rule.get('supported_methods',[]):raise ValueError('agent_rule_mismatch')
            self._methods[key]=copy.deepcopy(item)
        if set(self._methods)!={(a,m) for a,ms in AGENTS.items() for m in ms}:raise ValueError('incomplete_method_registry')

    def documents(self):return {'capabilities':copy.deepcopy(list(self._capabilities.values())),'rules':copy.deepcopy(list(self._rules.values())),'methods':copy.deepcopy(list(self._methods.values()))}

    def dependencies(self,agent,methods):
        caps=[];rules=[]
        for method in methods:
            entry=self._methods.get((agent,method))
            if not entry:raise ValueError('method_not_registered')
            caps.extend(entry['required_capabilities']);rules.extend(entry['required_rules'])
        return ([copy.deepcopy(self._capabilities[c]) for c in dict.fromkeys(caps)],[copy.deepcopy(self._rules[r]) for r in dict.fromkeys(rules)])

    def readiness(self,agent,methods):
        caps,rules=self.dependencies(agent,methods)
        if any(c['state']!='published' for c in caps):return 'capability_not_ready'
        if any(r['state']!='published' for r in rules):return 'rule_not_ready'
        return None

    def freeze(self,agent,methods,plugins):
        reason=self.readiness(agent,methods)
        if reason:raise ValueError(reason)
        caps,rules=self.dependencies(agent,methods)
        frozen=[]
        for cap in caps:
            matches=[p for p in plugins if p['id']==cap['plugin_id']]
            if len(matches)!=1 or not compatible(matches[0]['version'],cap['compatible_versions']) or matches[0].get('manifest',{}).get('tools')!=cap['tool_ids']:raise ValueError('facts_dependency_unavailable')
            if any(p['id']!=cap['plugin_id'] and set(p.get('manifest',{}).get('tools',[]))&set(cap['tool_ids']) for p in plugins):raise ValueError('facts_dependency_unavailable')
            frozen.append({**cap,'plugin_version':matches[0]['version']})
        value={**VERSIONS,'agent_id':agent,'methods':list(methods),'capabilities':frozen,'rules':rules}
        return {**value,'digest':digest(value)}

    def validate(self,frozen,agent,methods,plugins):
        # Re-evaluate current release state: frozen publication never overrides revocation.
        if frozen!=self.freeze(agent,methods,plugins):raise ValueError('registry_snapshot_mismatch')

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def load():
    root=Path(__file__).with_name('data')
    return Registry(*(json.loads((root/(name+'.json')).read_text()) for name in ('capabilities','rules','methods')))

REGISTRY=load()


def rule_bindings(frozen):
    result=[]
    for rule in frozen['rules']:
        for module in METHODS[rule['supported_methods'][0]]:
            result.append({'module':module,'rule_id':rule['id'],'version':rule['version'],'implementation':rule['implementation']})
    return result
