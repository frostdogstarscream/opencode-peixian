// Fixed platform subprocess. All network reads still traverse the account Relay.
import { pathToFileURL } from 'node:url';
const chunks=[];for await (const chunk of process.stdin) chunks.push(chunk);
const input=JSON.parse(Buffer.concat(chunks).toString('utf8'));
const output=process.stdout.write.bind(process.stdout);
process.stdout.write=()=>true;process.stderr.write=()=>true;
for(const name of ['log','warn','error','info','debug'])console[name]=()=>{};
try {
 let value;
 if(input.action==='compile') {
  const {compile}=await import(pathToFileURL(input.engine).href);
  value=compile(input.context,input.responses);
 } else {
  const {createPlatform}=await import(pathToFileURL(input.platform_client).href);
  const {default:factory}=await import(pathToFileURL(input.entry).href);
  const plugin=await factory({},input.options,createPlatform(input.platform_connections));
  if(Object.keys(plugin.tool).length!==1||!plugin.tool[input.tool])throw new Error('invalid_module');
  value=JSON.parse(await plugin.tool[input.tool].execute(input.args ?? {}));
 }
 output(JSON.stringify({ok:true,value}));
} catch { output(JSON.stringify({ok:false}));process.exitCode=1; }
