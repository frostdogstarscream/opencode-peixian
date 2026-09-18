const names = ["涉赌案件资料整理", "盗窃案件时空资料核对"]
export function displayName(value = "") {
  for (const name of names) if ([name, name + "（合成演示）", name + "（代码核对演示）"].includes(value)) return name
  return value
}
