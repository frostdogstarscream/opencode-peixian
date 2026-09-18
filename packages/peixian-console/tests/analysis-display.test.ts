import { test, expect } from "bun:test"
import { displayName } from "../src/analysis-display"
test("known labels only; user-authored sentences and unknown names remain verbatim",()=>{
 expect(displayName("涉赌案件资料整理（代码核对演示）")).toBe("涉赌案件资料整理")
 expect(displayName("盗窃案件时空资料核对（合成演示）")).toBe("盗窃案件时空资料核对")
 expect(displayName("用户自己写的合成演示内容")).toBe("用户自己写的合成演示内容")
})
