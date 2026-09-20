const MODULE = "calls";
const TOOL = "peixian_get_calls_records";
function empty(args) {
  if (!args || typeof args !== 'object' || Array.isArray(args) || Object.keys(args).length) throw new Error('此查询不接受筛选参数。');
}
export default async function plugin(_context, _options, platform) {
  return { tool: { [TOOL]: {
    description: "只查询话单资料的固定已接入资料；不接受任意人员、时间或模块参数。", args: {},
    async execute(args) {
      empty(args);
      const response = await platform.connections.request('records', {method:'POST',path:'/v1/demo/records/query',json:{module:MODULE}});
      const data = response.data;
      if (response.status !== 200 || data?.module !== MODULE || data?.synthetic !== true || data?.data_status !== 'complete' || !Array.isArray(data.records)
          || data.returned_count !== data.records.length || data.total_count !== data.records.length || data.has_more !== false
          || typeof data.snapshot_id !== 'string' || !data.snapshot_id || typeof data.rule_version !== 'string') throw new Error('资料响应不完整或模块不匹配，本次未取得可核对结果。');
      if (data.records.some(row => !row || typeof row.record_id !== 'string' || !row.record_id) || new Set(data.records.map(row=>row.record_id)).size !== data.records.length) throw new Error('资料编号缺失或重复。');
      return JSON.stringify({items:data.records,module:MODULE,data_status:data.data_status,returned_count:data.returned_count,total_count:data.total_count,has_more:false,snapshot_id:data.snapshot_id,source:'已接入资料服务',synthetic:true,rule_version:data.rule_version,rule_status:data.rule_status});
    }
  }}};
}
export async function test(_options, platform) {
  const response=await platform.connections.request('records',{method:'GET',path:'/health'});
  return {ok:response.status===200&&response.data?.ok===true&&response.data?.synthetic===true,message:'资料服务健康检查完成'};
}
