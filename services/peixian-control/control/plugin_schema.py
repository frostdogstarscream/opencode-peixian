"""Supported business-form schemas and recursive secret handling."""
from copy import deepcopy

SCALARS = {"string", "number", "integer", "boolean"}


def secret(schema):
    return bool(schema.get("writeOnly") or schema.get("format") == "password")


def validate_form(schema, depth=0):
    if not isinstance(schema, dict) or depth > 5:
        raise ValueError("配置表单结构过深或无效")
    kind = schema.get("type")
    if kind in SCALARS:
        if "enum" in schema and (not isinstance(schema["enum"], list) or len(schema["enum"]) > 100):
            raise ValueError("配置选项过多")
        return
    if kind == "array":
        item = schema.get("items", {})
        if not isinstance(item, dict) or item.get("type") not in SCALARS or secret(item) or secret(schema):
            raise ValueError("列表字段仅支持非凭据的文字、数字或布尔值")
        validate_form(item, depth + 1)
        return
    if kind != "object" or secret(schema) or not isinstance(schema.get("properties"), dict):
        raise ValueError("配置表单需要明确列出字段，不支持原始 JSON 或自由对象")
    if schema.get("additionalProperties") is not False or len(schema["properties"]) > 64:
        raise ValueError("配置对象必须关闭额外字段，且最多支持 64 个字段")
    for value in schema["properties"].values():
        validate_form(value, depth + 1)


def redact(schema, value):
    if not isinstance(schema, dict) or schema.get("type") not in SCALARS | {"object", "array"}:
        return ({}, None) if isinstance(value, dict) else (None, None)
    if secret(schema):
        return None, bool(value)
    if schema.get("type") == "object" and isinstance(value, dict):
        safe, configured = {}, {}
        for key, item in value.items():
            if key not in schema.get("properties", {}):
                continue
            field = schema["properties"][key]
            clean, state = redact(field, item)
            if not secret(field):
                safe[key] = clean
            if state is not None:
                configured[key] = state
        return safe, configured or None
    return deepcopy(value), None


def merge_secrets(schema, incoming, previous):
    if secret(schema):
        return deepcopy(previous) if incoming in (None, "") and previous is not None else incoming
    if schema.get("type") == "object" and isinstance(incoming, dict):
        result = deepcopy(incoming)
        prior = previous if isinstance(previous, dict) else {}
        for key, field in schema.get("properties", {}).items():
            if key in incoming or key in prior:
                if field.get("type") == "object" or secret(field):
                    result[key] = merge_secrets(field, incoming.get(key, {} if field.get("type") == "object" else None), prior.get(key))
        return result
    return deepcopy(incoming)


def secret_values(schema, value):
    if secret(schema):
        return [value] if isinstance(value, str) and value else []
    if schema.get("type") == "object" and isinstance(value, dict):
        return [item for key, field in schema.get("properties", {}).items() for item in secret_values(field, value.get(key))]
    return []
