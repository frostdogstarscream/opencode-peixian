// Platform core, not a user-installable plugin. Host adapters must supply durable
// Run-scoped storage, admitted plugin dispatch and audit, never raw credentials.
import { compile, checkClaims } from './engine.mjs';
export const METHODS=Object.freeze({night:['night'],companions:['portrait'],funds:['funds'],relations:['lookup','composite'],calls:['calls'],vehicles:['vehicle']});
export function createCoordinator({read,write,invoke,authorize,audit,scenarios,validate}) {
 const flights=new Map();
 function checked(identity) {
  for(const key of ['uid','run_id','revision']) if(identity?.[key]===undefined||identity[key]===null) throw new Error('missing_execution_identity');
  return JSON.stringify([identity.uid,identity.run_id,identity.revision]);
 }
 async function exclusive(identity,action) {
  const key=checked(identity);if(flights.has(key))throw new Error('facts_operation_in_progress');
  const task=Promise.resolve().then(action);flights.set(key,task);
  try{return await task;}finally{if(flights.get(key)===task)flights.delete(key);}
 }
 return Object.freeze({
  async prepare(identity,{scenario_id,methods},signal) {
   return exclusive(identity,async()=>{
    if(!Object.hasOwn(scenarios,scenario_id)||!Array.isArray(methods)||!methods.length||methods.length>6||new Set(methods).size!==methods.length||methods.some(m=>!Object.hasOwn(METHODS,m)))throw new Error('invalid_method_selection');
    const context=scenarios[scenario_id];const modules=[...new Set(methods.flatMap(m=>METHODS[m]))];
    // Method selection cannot expand the fixed scene's admitted module scope.
    if(modules.some(m=>!context.required_modules.includes(m)))throw new Error('module_outside_scenario');
    const state=await read(identity)??{scenario_id,modules:{},table:null};
    if(state.scenario_id!==scenario_id)throw new Error('run_scenario_conflict');
    for(const module of modules) {
     signal?.throwIfAborted();
     await authorize(identity,module);
     if(state.modules[module])continue; // pending/error/unknown is never automatically resent
     state.modules[module]={status:'pending'};await write(identity,state);
     await audit(identity,{module,status:'running'});
     let response;
     try {response=await invoke(identity,module,signal);} catch {
      state.modules[module]={status:signal?.aborted?'cancelled':'unknown'};
      await write(identity,state);await audit(identity,{module,status:state.modules[module].status});continue;
     }
     signal?.throwIfAborted();
     await authorize(identity,module);
     if(!validate(module,response,context)) {
      state.modules[module]={status:'rejected'};await write(identity,state);await audit(identity,{module,status:'rejected'});continue;
     }
     state.modules[module]={status:'completed',response};await write(identity,state);await audit(identity,{module,status:'completed'});
    }
    const responses=Object.fromEntries(modules.filter(m=>state.modules[m]?.status==='completed').map(m=>[m,state.modules[m].response]));
    state.table=compile({...context,required_modules:modules},responses);
    state.methods=methods;await write(identity,state);
    return structuredClone(state.table);
   });
  },
  async check(identity,{scenario_id,claims},signal) {
   return exclusive(identity,async()=>{
    signal?.throwIfAborted();const state=await read(identity);
    if(!state?.table||state.scenario_id!==scenario_id)throw new Error('prepare_required');
    for(const row of state.table.summary)await authorize(identity,row.module);
    return checkClaims(state.table,claims);
   });
  }
 });
}
