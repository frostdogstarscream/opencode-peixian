import { For, Index, Show } from "solid-js"
import { Button, Field } from "./components"
import { safeMessage } from "./api"
import type { CredentialState, Json, Schema } from "./types"

function scalar(schema: Schema) {
  return (
    ["string", "number", "integer", "boolean"].includes(schema.type ?? "") &&
    (!schema.enum ||
      schema.enum.every((value) => value !== null && ["string", "number", "boolean"].includes(typeof value)))
  )
}
export function supportsSchema(schema: Schema): boolean {
  if (schema.type === "object" || schema.properties)
    return !!schema.properties && Object.values(schema.properties).every(supportsSchema)
  if (schema.type === "array")
    return (
      !!schema.items &&
      scalar(schema.items) &&
      !schema.items.writeOnly &&
      schema.items.format !== "password" &&
      !schema.writeOnly
    )
  return scalar(schema)
}
function initial(schema: Schema): Json {
  return (
    schema.default ??
    schema.enum?.[0] ??
    (schema.type === "boolean" ? false : schema.type === "number" || schema.type === "integer" ? 0 : "")
  )
}
function ScalarInput(props: {
  schema: Schema
  value: Json | undefined
  required?: boolean
  label: string
  onChange: (value: Json) => void
}) {
  const secret = () => !!(props.schema.writeOnly || props.schema.format === "password")
  return (
    <Show
      when={props.schema.enum}
      fallback={
        <Show
          when={props.schema.type === "boolean"}
          fallback={
            <input
              aria-label={props.label}
              type={
                secret()
                  ? "password"
                  : props.schema.type === "number" || props.schema.type === "integer"
                    ? "number"
                    : "text"
              }
              autocomplete={secret() ? "new-password" : "off"}
              value={typeof props.value === "string" || typeof props.value === "number" ? String(props.value) : ""}
              required={props.required}
              min={props.schema.minimum}
              max={props.schema.maximum}
              minlength={props.schema.minLength}
              maxlength={props.schema.maxLength}
              pattern={props.schema.pattern}
              step={props.schema.type === "integer" ? 1 : "any"}
              onInput={(event) => {
                const value = event.currentTarget.value
                props.onChange(
                  props.schema.type === "number" || props.schema.type === "integer"
                    ? value === ""
                      ? null
                      : Number(value)
                    : value,
                )
              }}
            />
          }
        >
          <input
            aria-label={props.label}
            type="checkbox"
            checked={props.value === true}
            onChange={(event) => props.onChange(event.currentTarget.checked)}
          />
        </Show>
      }
    >
      <select
        aria-label={props.label}
        required={props.required}
        value={
          props.value === undefined || props.value === null
            ? ""
            : String(props.schema.enum?.findIndex((value) => value === props.value))
        }
        onChange={(event) =>
          props.onChange(
            event.currentTarget.value === "" ? null : props.schema.enum![Number(event.currentTarget.value)],
          )
        }
      >
        <option value="">请选择</option>
        <For each={props.schema.enum}>
          {(option, index) => <option value={index()}>{safeMessage(String(option))}</option>}
        </For>
      </select>
    </Show>
  )
}
export function SchemaFields(props: {
  schema: Schema
  value: Record<string, Json>
  onChange: (value: Record<string, Json>) => void
  configured?: CredentialState
}) {
  function update(key: string, value: Json) {
    props.onChange({ ...props.value, [key]: value })
  }
  return (
    <div class="schema-fields">
      <For each={Object.entries(props.schema.properties ?? {})}>
        {([key, field]) => {
          const value = () => props.value[key] ?? field.default
          const secret = () => !!(field.writeOnly || field.format === "password")
          const configured = () => (typeof props.configured === "object" ? props.configured[key] : props.configured)
          const required = () => props.schema.required?.includes(key) && !(secret() && configured() === true)
          const label = () => safeMessage(field.title ?? key)
          const values = () => (Array.isArray(value()) ? (value() as Json[]) : [])
          return (
            <Show
              when={supportsSchema(field)}
              fallback={
                <div class="notice">
                  <strong>{label()}</strong>
                  <p>此版本表单不支持，请联系管理员。</p>
                </div>
              }
            >
              <Show
                when={field.type === "object" || field.properties}
                fallback={
                  <Show
                    when={field.type === "array"}
                    fallback={
                      <Field
                        label={label()}
                        hint={
                          field.description
                            ? safeMessage(field.description)
                            : secret() && configured() === true
                              ? "已配置，留空保留现有凭据。"
                              : undefined
                        }
                        required={required()}
                      >
                        <ScalarInput
                          schema={field}
                          value={value()}
                          label={label()}
                          required={required()}
                          onChange={(value) => update(key, value)}
                        />
                      </Field>
                    }
                  >
                    <fieldset class="schema-group">
                      <legend>{label()}</legend>
                      <Show when={field.description}>
                        <p class="muted">{safeMessage(field.description)}</p>
                      </Show>
                      <Index each={values()}>
                        {(item, index) => (
                          <div class="array-item">
                            <ScalarInput
                              schema={field.items!}
                              value={item()}
                              label={label() + "第 " + (index + 1) + " 项"}
                              required
                              onChange={(value) =>
                                update(
                                  key,
                                  values().map((existing, at) => (at === index ? value : existing)),
                                )
                              }
                            />
                            <Button
                              type="button"
                              variant="ghost"
                              aria-label={"删除 " + label() + "第 " + (index + 1) + " 项"}
                              disabled={values().length <= (field.minItems ?? 0)}
                              onClick={() =>
                                update(
                                  key,
                                  values().filter((_, at) => at !== index),
                                )
                              }
                            >
                              删除
                            </Button>
                          </div>
                        )}
                      </Index>
                      <Show when={!values().length}>
                        <p class="muted">尚未添加内容</p>
                      </Show>
                      <Button
                        type="button"
                        icon="plus"
                        disabled={values().length >= (field.maxItems ?? 100)}
                        onClick={() => update(key, [...values(), initial(field.items!)])}
                      >
                        添加一项
                      </Button>
                    </fieldset>
                  </Show>
                }
              >
                <fieldset class="schema-group">
                  <legend>{label()}</legend>
                  <SchemaFields
                    schema={field}
                    value={
                      value() && typeof value() === "object" && !Array.isArray(value())
                        ? (value() as Record<string, Json>)
                        : {}
                    }
                    onChange={(nested) => update(key, nested)}
                    configured={configured()}
                  />
                </fieldset>
              </Show>
            </Show>
          )
        }}
      </For>
    </div>
  )
}
