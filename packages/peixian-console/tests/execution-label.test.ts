import { test, expect } from "bun:test"
import { executionLabel } from "../src/execution-label"
test("business enums are localized, unknown enums do not leak", () => {
 expect(executionLabel("completed")).toBe("已完成")
 expect(executionLabel("empty")).toBe("暂无有效资料")
 expect(executionLabel("new_internal_phase")).toBe("状态待确认")
})
