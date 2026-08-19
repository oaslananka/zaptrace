"""Tests for enterprise RBAC and audit trail."""

from __future__ import annotations

from zaptrace.enterprise.rbac import (
    AuditEvent,
    Permission,
    Role,
    Team,
    TeamMember,
    check_permission,
    role_permissions_table,
)


def _member(role: Role) -> TeamMember:
    return TeamMember(user_id=f"user-{role.value}", display_name=role.value.title(), role=role)


class TestRolePermissions:
    def test_admin_has_all_permissions(self) -> None:
        admin = _member(Role.ADMIN)
        for perm in Permission:
            assert perm in admin.effective_permissions, f"Admin missing {perm}"

    def test_viewer_can_only_read(self) -> None:
        viewer = _member(Role.VIEWER)
        assert Permission.DESIGN_READ in viewer.effective_permissions
        assert Permission.DESIGN_WRITE not in viewer.effective_permissions
        assert Permission.TEAM_ADMIN not in viewer.effective_permissions

    def test_engineer_can_write(self) -> None:
        eng = _member(Role.ENGINEER)
        assert Permission.DESIGN_WRITE in eng.effective_permissions
        assert Permission.PROOF_APPROVE not in eng.effective_permissions

    def test_lead_can_approve(self) -> None:
        lead = _member(Role.LEAD)
        assert Permission.PROOF_APPROVE in lead.effective_permissions

    def test_roles_are_additive(self) -> None:
        """Higher roles include all permissions of lower roles."""
        viewer_perms = _member(Role.VIEWER).effective_permissions
        engineer_perms = _member(Role.ENGINEER).effective_permissions
        assert viewer_perms.issubset(engineer_perms)


class TestGranularOverrides:
    def test_extra_grant_gives_permission(self) -> None:
        viewer = _member(Role.VIEWER)
        viewer.grants.add(Permission.DESIGN_WRITE)
        assert Permission.DESIGN_WRITE in viewer.effective_permissions

    def test_revocation_removes_permission(self) -> None:
        eng = _member(Role.ENGINEER)
        eng.revocations.add(Permission.DESIGN_WRITE)
        assert Permission.DESIGN_WRITE not in eng.effective_permissions


class TestCheckPermission:
    def test_allowed_returns_true(self) -> None:
        admin = _member(Role.ADMIN)
        assert check_permission(admin, Permission.TEAM_ADMIN)

    def test_denied_returns_false(self) -> None:
        viewer = _member(Role.VIEWER)
        assert not check_permission(viewer, Permission.DESIGN_WRITE)

    def test_audit_log_is_appended(self) -> None:
        eng = _member(Role.ENGINEER)
        log: list[AuditEvent] = []
        check_permission(eng, Permission.DESIGN_WRITE, resource_id="design-abc", audit_log=log)
        assert len(log) == 1
        assert log[0].user_id == "user-engineer"
        assert log[0].allowed
        assert log[0].resource_id == "design-abc"

    def test_denied_event_is_recorded(self) -> None:
        viewer = _member(Role.VIEWER)
        log: list[AuditEvent] = []
        check_permission(viewer, Permission.PLUGIN_INSTALL, audit_log=log)
        assert not log[0].allowed


class TestTeam:
    def test_get_member_by_id(self) -> None:
        team = Team(
            team_id="t1",
            name="Firmware",
            members=[_member(Role.ENGINEER), _member(Role.VIEWER)],
        )
        assert team.get_member("user-engineer") is not None
        assert team.get_member("nobody") is None

    def test_team_to_dict(self) -> None:
        team = Team(team_id="t1", name="Test", members=[_member(Role.LEAD)])
        d = team.to_dict()
        assert d["team_id"] == "t1"
        assert len(d["members"]) == 1


def test_role_permissions_table() -> None:
    table = role_permissions_table()
    assert "viewer" in table
    assert "admin" in table
    assert len(table["admin"]) > len(table["viewer"])
