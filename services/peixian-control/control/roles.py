"""Server-owned console capabilities; role names never come from a request header."""

CAPABILITIES = {
    "super_admin": ("users.manage", "admins.manage", "models.manage", "audit.read",
                    "plugins.manage", "templates.manage", "runtimes.manage", "jobs.read", "connections.manage"),
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
    "connections_list": "connection.list", "connection_create": "connection.create",
    "connection_edit": "connection.update", "connection_delete": "connection.delete",
    "connection_test": "connection.test", "plugin_connections_get": "plugin.connections_read",
    "plugin_connections_put": "plugin.connections_update",
    "maintenance_state": "maintenance.read", "maintenance_set": "maintenance.update",
    "recovery_action": "runtime.recovery",
}
