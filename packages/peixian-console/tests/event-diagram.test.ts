import {describe,test,expect} from "bun:test"
import {isDiagram,exportName} from "../src/event-diagram"
const graph={version:"1.0",status:"ready",scenario_id:"DEMO-CASE-THEFT",timezone:"Asia/Shanghai",window_start:"start",window_end:"end",scenario_snapshot_id:"s",records_snapshot_id:"r",rule_version:"v",legend:"time",aliases:[],missing:[],pages:[{number:1,mermaid:'flowchart TB\nn1["中文记录"]',nodes:[]}]}
describe("trusted diagram contract",()=>{
 test("recognizes current graph and rejects unknown versions",()=>{expect(isDiagram(graph)).toBe(true);expect(isDiagram({...graph,version:"2.0"})).toBe(false)})
 test("does not permit executable directives, HTML or links",()=>{for(const payload of ['%%{init: {}}%%','click n1 "https://x"','<script>x</script>','style n1 fill:red'])expect(isDiagram({...graph,pages:[{...graph.pages[0],mermaid:'flowchart TB\n'+payload}]})).toBe(false)})
 test("bounds source size and requires complete node shape",()=>{expect(isDiagram({...graph,pages:[{...graph.pages[0],mermaid:'flowchart TB\n'+'a'.repeat(65537)}]})).toBe(false);expect(isDiagram({...graph,pages:[{...graph.pages[0],nodes:[{id:'n1'}]}]})).toBe(false)})
 test("download name cannot inject path components",()=>{expect(exportName({...graph,scenario_id:'../../unsafe'} as never,2,'png')).toBe('事件脉络图-______unsafe-第2页.png')})
})
