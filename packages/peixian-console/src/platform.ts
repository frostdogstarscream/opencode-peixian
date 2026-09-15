export type Platform = { name: string; short_name: string; description: string }

export const defaultPlatform: Platform = {
  name: "Agent 工作台",
  short_name: "AI",
  description: "你的智能助手与工具空间",
}

export function platformMetadata(value: Partial<Platform> | null): Platform {
  return Object.fromEntries(
    Object.entries(defaultPlatform).map(([key, fallback]) => {
      const supplied = value?.[key as keyof Platform]
      return [key, typeof supplied === "string" && supplied.trim() ? supplied.trim() : fallback]
    }),
  ) as Platform
}
