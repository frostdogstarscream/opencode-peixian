#!/usr/bin/env python3
"""One seven-request acceptance, across two accounts; no model retries.

Must run on the isolated deployment host. Probe the actual Agent registry first.
Credentials remain in memory. Only newly copied Skill IDs are deleted on exit.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import time
import urllib.parse

from accept_agent_behavior_with_template import acceptance_class, CASES, TEMPLATE_NAME
from agent_acceptance_evidence import current_turn, validate_chain
from records_service import MODULES
from fixture_profiles import load_profile

READ_AGENT = r'''
from pathlib import Path
import json,sys,urllib.request,base64
path=json.loads(sys.stdin.readline())["path"]
password=Path("/run/secrets/opencode-password").read_text().strip()
headers={"Authorization":"Basic "+base64.b64encode(("opencode:"+password).encode()).decode()}
with urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:4096"+path,headers=headers),timeout=20) as r:
 print(r.read().decode())
'''
PROBE_AGENT = r'''
from pathlib import Path
import json,urllib.request,urllib.parse,base64
password=Path("/run/secrets/opencode-password").read_text().strip()
headers={"Authorization":"Basic "+base64.b64encode(("opencode:"+password).encode()).decode()}
def get(path):
 with urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:4096"+path,headers=headers),timeout=20) as r:return json.load(r)
cfg=json.loads(Path("/managed/opencode.json").read_text())
ids=get("/experimental/tool/ids?directory=/workspace")
result={"registered":[x for x in ids if x.startswith("peixian_get_")],"models":[],"permissions":{k:v for k,v in cfg.get("permission",{}).items() if k.startswith("peixian_get_")}}
for provider,value in cfg.get("provider",{}).items():
 for model in value.get("models",{}):
  rows=get("/experimental/tool?"+urllib.parse.urlencode({"directory":"/workspace","provider":provider,"model":model}))
  result["models"].append({"provider":provider,"model":model,"tools":[x for x in rows if x["id"].startswith("peixian_get_")]})
print(json.dumps(result))
'''


def container_json(container, code, payload=None):
    # Code is fixed above; model/user inputs never become a shell command.
    if payload is None:
        command=["docker","exec","-i",container,"python3","-"]
        data=code
    else:
        command=["docker","exec","-i",container,"python3","-c",code]
        data=json.dumps(payload)+"\n"
    result=subprocess.run(command,input=data,text=True,capture_output=True,timeout=30)
    if result.returncode:
        raise RuntimeError("agent_read_failed")
    return json.loads(result.stdout)


def agent_messages(container, sid):
    if not sid.startswith("ses_") or not all(x.isalnum() or x=="_" for x in sid):
        raise ValueError("invalid_session_id")
    return container_json(container,READ_AGENT,{"path":"/session/"+sid+"/message?directory=/workspace"})


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--deployment-root",type=Path,required=True)
    parser.add_argument("--report",type=Path,required=True)
    parser.add_argument("--fixture-profile",choices=["legacy","enhanced"],required=True)
    args=parser.parse_args()
    expected_responses,fixture_identity=load_profile(args.fixture_profile)
    root=args.deployment_root.resolve()
    assert root.name=="peixian-alignment-20260917"
    # Exclusive creation prevents accidentally repeating a paid acceptance run.
    with args.report.open("x") as f:f.write("{}")
    api=acceptance_class(root)(root)
    report={"scope":"two_accounts_seven_requests","model_retries":0,"fixture":fixture_identity,"registry":{},"cases":[],"temporary_skills":{},"cleanup":{}}
    clients={};containers={};original={};temporary={}
    def save():args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    try:
        expected={"peixian_get_"+module+"_records" for module in MODULES}
        model=api.state["model"]
        for name in dict.fromkeys(x[0] for x in CASES):
            client=api.login(name);clients[name]=client
            me=api.request(client,"GET","/me");uid=me["user"]["id"]
            ids=subprocess.check_output(["docker","ps","-q","--filter","label=peixian.uid="+uid],text=True).split()
            records=json.loads(subprocess.check_output(["docker","inspect",*ids],text=True))
            matches=[x for x in records if x["Config"]["Labels"].get("com.docker.compose.service")=="agent" and x["Config"]["Labels"].get("peixian.deployment")==root.name]
            assert len(matches)==1
            containers[name]=matches[0]["Name"].lstrip("/")
            found=container_json(containers[name],PROBE_AGENT)
            assert expected<=set(found["registered"])
            selected=next(x for x in found["models"] if x["model"]==model)
            assert expected<={x["id"] for x in selected["tools"]}
            assert all(found["permissions"].get(x)=="allow" for x in expected)
            assert all(x.get("parameters",{}).get("properties")=={} for x in selected["tools"])
            report["registry"][name]=found;save()
        print("both_actual_registries_verified",flush=True)
        for name,client in clients.items():
            original[name]={x["id"] for x in api.request(client,"GET","/skills")["items"]}
            templates=api.request(client,"GET","/templates")["items"]
            matches=[x for x in templates if x["name"]==TEMPLATE_NAME];assert len(matches)==1
            copied=api.request(client,"POST","/templates/"+matches[0]["id"]+"/copy",json={})
            temporary[name]=copied["id"];report["temporary_skills"][name]={"id":copied["id"],"status":"created"};save()
            api.ready(client,seconds=300)
            skill=next(x for x in api.request(client,"GET","/skills")["items"] if x["id"]==copied["id"])
            report["temporary_skills"][name]["name"]=skill["name"]
            assert api.request(client,"POST","/skills/"+copied["id"]+"/test",json={})["ok"]
            report["temporary_skills"][name]["status"]="loaded";save()
        for name,module,label in CASES:
            client=clients[name]
            sid=api.request(client,"POST","/sessions",json={"title":"七工具完整链验收-"+module})["id"]
            case={"account":name,"module":module,"session_id":sid,"status":"submitting"};report["cases"].append(case);save()
            skill_name=report["temporary_skills"][name]["name"]
            prompt=(f"这是只读合成资料工具验收。请先调用 skill 工具加载所选个人技能《{skill_name}》，"
                    f"然后且仅调用一次 peixian_get_{module}_records 工具，参数为 {{}}，查询{label}合成资料。"
                    "不要调用其他工具。最终回答仅简短说明这是合成演示资料，并列出工具真实返回的 module、"
                    "synthetic、snapshot_id、data_status、returned_count 及全部 record_id。"
                    "不得生成风险评分或真实身份推断。未取得工具结果则明确失败，不编造内容。")
            start=time.monotonic()
            try:
                api.request(client,"POST","/sessions/"+sid+"/messages",json={"text":prompt,"model_id":model,"skill_ids":[temporary[name]]})
                while time.monotonic()-start<180:
                    messages=api.request(client,"GET","/sessions/"+sid+"/messages")["items"]
                    answers=current_turn(messages)
                    if any(x["info"].get("error") for x in answers):raise RuntimeError("model_request_failed")
                    if answers and answers[-1]["info"].get("time",{}).get("completed") and answers[-1]["info"].get("finish") in ("stop","end_turn"):break
                    time.sleep(2)
                else:raise RuntimeError("model_result_unknown")
                result=validate_chain(agent_messages(containers[name],sid),messages,expected_responses[module],skill_name)
                case.update(status="passed",seconds=round(time.monotonic()-start,2),**result)
            except Exception as exc:
                # No prompt retries. Abort only this synthetic session if outcome is unknown.
                case.update(status="failed",reason=type(exc).__name__+":"+str(exc)[:160])
                try:api.request(client,"POST","/sessions/"+sid+"/abort",json={})
                except Exception:case["abort_unconfirmed"]=True
            save();print(json.dumps({k:v for k,v in case.items() if k!="answer"},ensure_ascii=False),flush=True)
            if case["status"]!="passed":break
    finally:
        for name,skill_id in temporary.items():
            try:
                api.request(clients[name],"DELETE","/skills/"+skill_id)
                api.ready(clients[name],seconds=300)
                ids={x["id"] for x in api.request(clients[name],"GET","/skills")["items"]}
                assert skill_id not in ids and original[name]<=ids
                report["cleanup"][name]="temporary_deleted_existing_preserved_runtime_ready"
            except Exception as exc:report["cleanup"][name]="failed:"+type(exc).__name__
            save()
        api.clients.close()
    report["passed"]=(len(report["cases"])==7 and all(x["status"]=="passed" for x in report["cases"]) and len(report["cleanup"])==2 and all(v.startswith("temporary_deleted") for v in report["cleanup"].values()))
    save();print("acceptance_passed="+str(report["passed"]),flush=True)
    if not report["passed"]:raise SystemExit(1)


if __name__=="__main__":main()
