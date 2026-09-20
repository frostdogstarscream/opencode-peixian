"""Generate synthetic UI fixtures from the same verified backend projection."""
import json
from control.scenario_facts import TABLES, PREPARE, CHECK, review
from control.scenario_evidence import project
from control.scenario_presentation import presentation

if __name__ == "__main__":
    fixtures={}
    for sid in ("DEMO-CASE-THEFT", "DEMO-CASE-GAMBLING"):
        table=next(t for t in TABLES if t["scenario_id"]==sid and t["scenario_snapshot_id"]=="demo1005" and t["data_status"]=="complete")
        claims=[{k:f[k] for k in ("fact_id","statement","source_ids")} for f in table["facts"][:5]]
        messages=[{"info":{"id":"request","role":"user"}},{"info":{"id":"tool-message","role":"assistant"},"parts":[
            {"type":"tool","tool":PREPARE,"state":{"status":"completed","input":{"scenario_id":sid},"output":json.dumps(table)}},
            {"type":"tool","tool":CHECK,"state":{"status":"completed","input":{"scenario_id":sid,"claims":claims},"output":json.dumps(review(table,claims))}}]}]
        result=project(messages,True)
        result["diagram"]["run_id"]="run_demo"
        result["presentation"]=presentation(result,messages)
        fixtures[sid]=result
    print(json.dumps(fixtures,ensure_ascii=False,indent=2))
