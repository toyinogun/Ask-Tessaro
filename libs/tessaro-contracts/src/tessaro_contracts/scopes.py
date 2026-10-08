"""Tool scopes (PRD 8.2). OPA maps roles to these; a contract names exactly one."""

from enum import StrEnum


class Scope(StrEnum):
    """Every scope a tool can require. A value ending in `:write` is a write scope."""

    IT_READ = "it:read"
    HR_READ = "hr:read"
    FINANCE_READ = "finance:read"
    WORKPLACE_READ = "workplace:read"
    KB_READ = "kb:read"
    QUEUE_HANDOFF = "queue:handoff"
    WORKFLOW_READ = "workflow:read"
    TEAM_READ = "team:read"
    IT_READ_ANY = "it:read_any"
    WORKFLOW_READ_ANY = "workflow:read_any"
    HR_READ_ANY = "hr:read_any"
    IDENTITY_WRITE = "identity:write"
    IT_WRITE = "it:write"
    WORKPLACE_WRITE = "workplace:write"

    @property
    def is_write(self) -> bool:
        """True for write scopes, which only workflow worker tokens may use."""
        return self.value.endswith(":write")
