"""Closed, versioned Agent documents; capabilities remain method-owned."""
SCHEMA = {'type':'object','additionalProperties':False,'properties':{
    'schema_version':{'const':'agent-profile-v1'},
    'id':{'type':'string','pattern':'^[a-z][a-z0-9-]{1,63}$'},
    'version':{'type':'string','pattern':r'^\d+\.\d+\.\d+$'},
    'name':{'type':'string','minLength':1},'description':{'type':'string','minLength':1},
    'domain':{'enum':['gambling','theft']},
    'scenario_ids':{'type':'array','minItems':1,'uniqueItems':True,'items':{'enum':['DEMO-CASE-GAMBLING','DEMO-CASE-THEFT']}},
    'default_scenario_id':{'enum':['DEMO-CASE-GAMBLING','DEMO-CASE-THEFT']},
    'official_method_ids':{'type':'array','minItems':1,'uniqueItems':True,'items':{'type':'string'}},
    'intents':{'type':'object','required':['integrated_analysis'],'minProperties':1,'additionalProperties':False,'patternProperties':{
        '^(night_activity|companions_check|funds_analysis|relations_check|vehicle_activity|integrated_analysis)$':{
            'type':'object','additionalProperties':False,'required':['methods','keywords','official_method'],
            'properties':{'methods':{'type':'array','minItems':1,'uniqueItems':True,'items':{'enum':['night','companions','funds','relations','vehicles']}},
                          'keywords':{'type':'array','minItems':1,'uniqueItems':True,'items':{'type':'string','minLength':1}},
                          'official_method':{'type':'string'}}}}},
    'target_contract_profile':{'enum':['gambling-target-v1','theft-target-v1']},
    'claim_profile':{'enum':['gambling-claims-v1','theft-claims-v1']},
    'prompt_file':{'type':'string','pattern':r'^[a-z_]+\.md$'},
}}
SCHEMA['required']=list(SCHEMA['properties'])
