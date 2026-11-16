"""Deployment feature scopes: comma separated account IDs, or `*` for every account."""
import os


def members(env):
    return {value.strip() for value in os.getenv(env, '').split(',') if value.strip()}


def allowed(env, uid):
    values = members(env)
    return '*' in values or uid in values
