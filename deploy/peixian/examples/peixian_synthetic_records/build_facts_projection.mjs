import { readFile, writeFile } from 'node:fs/promises';
import { compile } from './facts-plugin/engine.mjs';
const data=JSON.parse(await readFile(new URL('./facts-plugin/fixtures.json',import.meta.url),'utf8'));
const tables=[];
for(const scenario of Object.values(data.scenarios)) for(let mask=0;mask<(1<<scenario.required_modules.length);mask++){
 const responses=Object.fromEntries(scenario.required_modules.filter((_,i)=>mask&(1<<i)).map(m=>[m,data.records[m]]));tables.push(compile(scenario,responses));
}
await writeFile(new URL('../../../../services/peixian-control/control/scenario_fact_tables.json',import.meta.url),JSON.stringify(tables,null,2)+'\n');
