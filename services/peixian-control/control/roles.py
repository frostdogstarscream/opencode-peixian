"""Server-owned console capabilities; role names never come from a request header."""

CAPABILITIES = {
    "super_admin": ("users.manage", "admins.manage", "models.manage", "audit.read",
                    "plugins.manage", "templates.manage", "runtimes.manage", "jobs.read"),
    "admin": ("users.manage", "models.manage", "audit.read"),
    "user": ("business.use",),
}


def capabilities(role):
    return list(CAPABILITIES.get(role, ()))


# Only these metadata events are exposed through the management audit API.
# Worker migration payloads and account business events are deliberately excluded.
MANAGEMENT_ACTIONS = {
    "users": "user.list", "user_create": "user.create", "user_edit": "user.update",
    "user_reset": "user.password_reset", "runtime_action": "runtime.manage",
    "jobs": "job.list", "audit": "audit.read", "models": "model.list",
    "model_create": "model.create", "model_edit": "model.update", "model_test": "model.test",
    "plugins": "plugin.list", "publish": "plugin.publish", "plugin_state": "plugin.publication_update",
    "templates": "template.list", "template_create": "template.create",
    "template_edit": "template.update", "template_delete": "template.delete",
}
