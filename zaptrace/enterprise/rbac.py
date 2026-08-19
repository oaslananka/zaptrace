"""Enterprise team RBAC and audit trail.

Defines the role-based access control (RBAC) model for ZapTrace enterprise
use: who can do what to which designs. This is a *policy definition layer* —
it declares roles, permissions, and the ``check_permission()`` enforcement
point. It does not implement authentication or session management.

The audit trail captures every permission decision so the access log is
complete and reviewable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class Permission(StrEnum):
    """Fine-grained permission atoms."""

    DESIGN_READ = "design:read"
    DESIGN_WRITE = "design:write"
    DESIGN_DELETE = "design:delete"
    DESIGN_EXPORT = "design:export"
    PROOF_READ = "proof:read"
    PROOF_APPROVE = "proof:approve"
    BOM_READ = "bom:read"
    BOM_EXPORT = "bom:export"
    ERC_RUN = "erc:run"
    DRC_RUN = "drc:run"
    LIBRARY_READ = "library:read"
    LIBRARY_WRITE = "library:write"
    PLUGIN_INSTALL = "plugin:install"
    TEAM_ADMIN = "team:admin"
    AUDIT_READ = "audit:read"


class Role(StrEnum):
    """Built-in team roles (ordered from least to most privileged)."""

    VIEWER = "viewer"
    REVIEWER = "reviewer"
    ENGINEER = "engineer"
    LEAD = "lead"
    ADMIN = "admin"


# Role → permission set (additive; higher roles include lower-role permissions)
_ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.VIEWER: {
        Permission.DESIGN_READ,
        Permission.PROOF_READ,
        Permission.BOM_READ,
        Permission.LIBRARY_READ,
    },
    Role.REVIEWER: {
        Permission.DESIGN_EXPORT,
        Permission.ERC_RUN,
        Permission.DRC_RUN,
    },
    Role.ENGINEER: {
        Permission.DESIGN_WRITE,
        Permission.BOM_EXPORT,
        Permission.LIBRARY_WRITE,
    },
    Role.LEAD: {
        Permission.PROOF_APPROVE,
        Permission.DESIGN_DELETE,
        Permission.AUDIT_READ,
    },
    Role.ADMIN: {
        Permission.PLUGIN_INSTALL,
        Permission.TEAM_ADMIN,
    },
}

# Role hierarchy for permission inheritance
_ROLE_ORDER = [Role.VIEWER, Role.REVIEWER, Role.ENGINEER, Role.LEAD, Role.ADMIN]


def _effective_permissions(role: Role) -> set[Permission]:
    """Return the full permission set for a role (including inherited)."""
    perms: set[Permission] = set()
    for r in _ROLE_ORDER:
        perms |= _ROLE_PERMISSIONS.get(r, set())
        if r == role:
            break
    return perms


# ---------------------------------------------------------------------------
# Team / user models
# ---------------------------------------------------------------------------


@dataclass
class TeamMember:
    """A team member with a role and optional resource-scoped overrides."""

    user_id: str
    display_name: str
    role: Role
    # Resource-scoped permission overrides: {resource_id: {+Permission} | {-Permission}}
    grants: set[Permission] = field(default_factory=set)  # extra permissions
    revocations: set[Permission] = field(default_factory=set)  # explicitly denied

    @property
    def effective_permissions(self) -> set[Permission]:
        return (_effective_permissions(self.role) | self.grants) - self.revocations

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "display_name": self.display_name,
            "role": self.role.value,
            "effective_permissions": sorted(p.value for p in self.effective_permissions),
        }


@dataclass
class Team:
    """A group of team members that share access to a set of designs."""

    team_id: str
    name: str
    members: list[TeamMember] = field(default_factory=list)

    def get_member(self, user_id: str) -> TeamMember | None:
        return next((m for m in self.members if m.user_id == user_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "name": self.name,
            "members": [m.to_dict() for m in self.members],
        }


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


@dataclass
class AuditEvent:
    """A single auditable access decision."""

    timestamp: str
    user_id: str
    permission: str
    resource_id: str | None
    allowed: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_permission(
    member: TeamMember,
    permission: Permission,
    *,
    resource_id: str | None = None,
    audit_log: list[AuditEvent] | None = None,
) -> bool:
    """Check whether *member* holds *permission* and record the decision.

    Args:
        member: The team member requesting access.
        permission: The permission required.
        resource_id: Optional resource being accessed (for audit trail context).
        audit_log: Optional list to append the :class:`AuditEvent` to.

    Returns:
        ``True`` if access is granted, ``False`` if denied.
    """
    allowed = permission in member.effective_permissions
    if audit_log is not None:
        audit_log.append(
            AuditEvent(
                timestamp=datetime.now(tz=UTC).isoformat(),
                user_id=member.user_id,
                permission=permission.value,
                resource_id=resource_id,
                allowed=allowed,
                reason="role grants" if allowed else "role denies",
            )
        )
    return allowed


def role_permissions_table() -> dict[str, list[str]]:
    """Return a human-readable table of roles and their effective permissions."""
    return {role.value: sorted(p.value for p in _effective_permissions(role)) for role in _ROLE_ORDER}
