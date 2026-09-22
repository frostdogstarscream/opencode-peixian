const METHOD="GET", PATH="/system/multiDimension/list";
export default async function plugin(_context,_options,platform) {
 return {tool:{peixian_query_warnings:{description:"读取已确认范围的来源预警列表。条件由平台冻结，无需参数。",args:{},async execute(args){
  const request=args?.request;
  if(!request || request.method!==METHOD || request.path!==PATH)throw new Error('查询范围未冻结或接口不匹配。');
  const response=await platform.connections.request('provider',request);
  if(response.status!==200 || response.data?.code!==200 || response.data?._fixture?.synthetic!==true)throw new Error('合成资料服务响应未通过核对。');
  return JSON.stringify(response.data);
 }}}};
}
export async function test(_options,platform){const r=await platform.connections.request('provider',{method:'GET',path:'/health'});return {ok:r.status===200&&r.data?.synthetic===true,message:'合成资料连接测试完成'};}
