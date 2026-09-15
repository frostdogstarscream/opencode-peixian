export type Json = null | boolean | number | string | Json[] | { [key: string]: Json }
export type Role = "super_admin" | "admin" | "user"
export type Capability =
  | "business.use"
  | "users.manage"
  | "admins.manage"
  | "models.manage"
  | "audit.read"
  | "plugins.manage"
  | "connections.manage"
  | "templates.manage"
  | "runtimes.manage"
  | "jobs.read"
export type User = {
  id: string
  username: string
  role: Role
  must_change_password: boolean
  active?: boolean
  model_ids?: string[]
  plugin_ids?: string[]
  runtime?: { id?: string; status: string; revision?: number; error?: string }
}
export type Auth = { user: User; csrf_token: string; capabilities: Capability[] }
export type Session = { id: string; title: string; status?: string; updated_at?: string; time?: { updated?: number } }
export type Part = {
  id?: string
  type: string
  text?: string
  tool?: string
  details?: { inputs?: Record<string, string | number | boolean>; outputs?: Record<string, string | number | boolean> }
  state?: { status?: string; title?: string; output?: string; error?: string }
}
export type Message = {
  info: {
    id: string
    role: string
    error?: { message?: string; data?: { message?: string } }
    time?: { created?: number; completed?: number }
    finish?: string
  }
  parts: Part[]
}
export type Model = {
  id: string
  name: string
  description?: string
  is_default?: boolean
  enabled?: boolean
  base_url?: string
  model_id?: string
  api_key_configured?: boolean
}
export type FileItem = {
  id: string
  name: string
  size?: number
  status?: string
  error?: string
  created_at?: string
  created?: number
}
export type Skill = {
  id: string
  name: string
  description?: string
  content?: string
  enabled?: boolean
  version?: number
  versions?: number[]
}
export type CredentialState = boolean | { [key: string]: CredentialState }
export type Schema = {
  type?: string
  title?: string
  description?: string
  properties?: Record<string, Schema>
  required?: string[]
  enum?: Json[]
  default?: Json
  writeOnly?: boolean
  format?: string
  minimum?: number
  maximum?: number
  minLength?: number
  maxLength?: number
  pattern?: string
  items?: Schema
  minItems?: number
  maxItems?: number
}
export type Plugin = {
  id: string
  name: string
  description?: string
  version: string
  versions?: (string | { version: string; enabled?: boolean; connections?: ConnectionAliases })[]
  connections?: ConnectionAliases
  connection_status?: Record<string, { ready: boolean; missing: string[] }>
  enabled?: boolean
  config_schema?: Schema
  schemas?: Record<string, Schema>
  installed?: {
    version: string
    enabled: boolean
    config?: Record<string, Json>
    credentials_configured?: CredentialState
    state?: string
    missing_connections?: string[]
  }
}
export type ConnectionAliases = Record<string, { description: string }>
export type ServiceConnection = {
  id: string
  name: string
  base_url: string
  auth_type: "none" | "bearer" | "api_key"
  header_name: string
  allowed_methods: string[]
  allowed_paths: string[]
  timeout_seconds: number
  max_response_bytes: number
  enabled: boolean
  secret_configured: boolean
  revision: number
}
export type Job = {
  id: string
  type?: string
  action?: string
  status: string
  user_id?: string
  uid?: string
  username?: string
  error?: string
  created_at?: string
  created?: number
}
export type Audit = {
  id: string
  action?: string
  actor?: string
  actor_role?: Role
  result?: "success" | "denied" | "failed"
  username?: string
  target?: string
  status?: string
  created_at?: string
  created?: number
  detail?: string
}
