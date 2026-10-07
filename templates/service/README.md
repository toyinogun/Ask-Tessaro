# Service template

Copy this with `just new-service <name> <namespace>`. It replaces `__SERVICE__` (the
dashed service name), `__PKG__` (the `tessaro_<name>` import name) and `__NAMESPACE__`,
creates `services/<name>/`, and writes the release values to `deploy/values/<name>.yaml`.
