from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "check_github_production_settings", ROOT / "scripts" / "check-github-production-settings.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _valid_settings() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    repository = {
        "security_and_analysis": {
            "dependabot_security_updates": {"status": "enabled"},
            "secret_scanning": {"status": "enabled"},
            "secret_scanning_push_protection": {"status": "enabled"},
        }
    }
    protection = {
        "required_status_checks": {"strict": True, "contexts": ["package", "Analyze (python)", "Analyze (actions)"]},
        "required_pull_request_reviews": {"required_approving_review_count": 1, "require_last_push_approval": True},
        "required_signatures": {"enabled": True},
        "enforce_admins": {"enabled": True},
        "required_linear_history": {"enabled": True},
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
        "required_conversation_resolution": True,
    }
    environment = {
        "can_admins_bypass": False,
        "protection_rules": [
            {"type": "branch_policy"},
            {"type": "required_reviewers", "reviewers": [{"type": "User", "reviewer": {"id": 1}}]},
        ],
        "deployment_branch_policy": {"custom_branch_policies": True},
    }
    secrets = {
        "secrets": [
            {"name": "GUILDBRIDGE_CODESIGN_PFX_BASE64"},
            {"name": "GUILDBRIDGE_CODESIGN_PFX_PASSWORD"},
            {"name": "GUILDBRIDGE_PRODUCTION_EVIDENCE_JSON"},
        ]
    }
    deployment_policies = {"branch_policies": [{"name": "v*", "type": "branch"}]}
    return repository, protection, environment, secrets, deployment_policies


def _valid_codeql_analyses(commit_sha: str = "a" * 40) -> list[dict[str, Any]]:
    return [
        {"tool": {"name": "CodeQL"}, "commit_sha": commit_sha, "category": "/language:python"},
        {"tool": {"name": "CodeQL"}, "commit_sha": commit_sha, "category": "/language:actions"},
    ]


def _valid_tag_rulesets() -> list[dict[str, Any]]:
    return [
        {
            "target": "tag",
            "enforcement": "active",
            "conditions": {"ref_name": {"include": ["refs/tags/v*"]}},
            "rules": [{"type": "creation"}, {"type": "update"}, {"type": "deletion"}],
        }
    ]


def test_validate_settings_accepts_complete_hosted_controls() -> None:
    module = _module()

    repository, protection, environment, secrets, deployment_policies = _valid_settings()

    assert module.validate_settings(
        repository,
        protection,
        environment,
        secrets,
        deployment_policies=deployment_policies,
        release_author_id=2,
        default_branch_commit_sha="a" * 40,
        codeql_analyses=_valid_codeql_analyses(),
        rulesets=_valid_tag_rulesets(),
    ) == []


def test_validate_settings_reports_missing_protection_and_secret_names() -> None:
    module = _module()
    repository, protection, environment, secrets, deployment_policies = _valid_settings()
    protection["required_signatures"] = {"enabled": False}
    protection["required_pull_request_reviews"] = {"required_approving_review_count": 0}
    environment["protection_rules"] = [{"type": "branch_policy"}]
    secrets["secrets"] = []

    errors = module.validate_settings(
        repository,
        protection,
        environment,
        secrets,
        deployment_policies=deployment_policies,
        open_codeql_alerts=[{"number": 42}],
    )

    assert "main branch must require at least one approving pull-request review" in errors
    assert "main branch must require approval after the latest push" in errors
    assert "main branch must require verified or signed commits" in errors
    assert "production-release environment is missing protection rules: required_reviewers" in errors
    assert any(error.startswith("production-release environment is missing required secret names:") for error in errors)
    assert "repository has open CodeQL alerts: 42" in errors


def test_error_category_does_not_echo_hosted_setting_values() -> None:
    module = _module()

    assert module._error_category("production-release environment is missing required secret names: SECRET_VALUE") == "production environment control"
    assert module._error_category("repository has open CodeQL alerts: 42") == "open CodeQL alert control"


def test_remediation_steps_are_ordered_and_do_not_include_secret_values() -> None:
    module = _module()

    steps = module.remediation_steps(
        [
            "main branch must require verified or signed commits",
            "production-release environment is missing required secret names: SECRET_VALUE",
            "repository has open CodeQL alerts: 42",
        ],
        environment_name="production-release",
    )

    assert steps == [
        "Update main branch protection to require current branches, one approving review, last-push approval, signed commits, "
        "linear history, resolved conversations, and the package plus both CodeQL checks.",
        "Configure the production-release environment with a v* protected-tag policy, administrator-bypass disabled, and an independent required reviewer.",
        "Add the required signing and evidence secret values to production-release in GitHub; do not place them in source control or command history.",
        "Resolve the open CodeQL alerts through reviewed fixes, then wait for fresh Python and Actions analyses on main.",
    ]
    assert "SECRET_VALUE" not in "\n".join(steps)


def test_validate_settings_requires_the_v_tag_environment_policy() -> None:
    module = _module()
    repository, protection, environment, secrets, _deployment_policies = _valid_settings()

    errors = module.validate_settings(
        repository,
        protection,
        environment,
        secrets,
        deployment_policies={"branch_policies": [{"name": "main", "type": "branch"}]},
    )

    assert "production-release environment must include the protected release tag policy: v*" in errors


def test_validate_settings_requires_an_immutable_public_tag_ruleset() -> None:
    module = _module()
    repository, protection, environment, secrets, deployment_policies = _valid_settings()

    errors = module.validate_settings(
        repository,
        protection,
        environment,
        secrets,
        deployment_policies=deployment_policies,
        rulesets=[
            {
                "target": "tag",
                "enforcement": "active",
                "conditions": {"ref_name": {"include": ["refs/tags/v*"]}},
                "rules": [{"type": "creation"}],
            }
        ],
    )

    assert "release tag ruleset for refs/tags/v* is missing protections: deletion, update" in errors


def test_validate_settings_requires_current_commit_codeql_for_python_and_actions() -> None:
    module = _module()
    repository, protection, environment, secrets, deployment_policies = _valid_settings()

    errors = module.validate_settings(
        repository,
        protection,
        environment,
        secrets,
        deployment_policies=deployment_policies,
        default_branch_commit_sha="a" * 40,
        codeql_analyses=[{"tool": {"name": "CodeQL"}, "commit_sha": "b" * 40, "category": "/language:python"}],
    )

    assert "current default-branch commit is missing CodeQL analyses: /language:actions, /language:python" in errors


def test_validate_settings_requires_an_assigned_environment_reviewer() -> None:
    module = _module()
    repository, protection, environment, secrets, deployment_policies = _valid_settings()
    environment["protection_rules"] = [{"type": "branch_policy"}, {"type": "required_reviewers", "reviewers": []}]

    errors = module.validate_settings(
        repository,
        protection,
        environment,
        secrets,
        deployment_policies=deployment_policies,
    )

    assert "production-release environment must assign at least one required reviewer" in errors


def test_validate_settings_rejects_the_release_author_as_the_only_reviewer() -> None:
    module = _module()
    repository, protection, environment, secrets, deployment_policies = _valid_settings()

    errors = module.validate_settings(
        repository,
        protection,
        environment,
        secrets,
        deployment_policies=deployment_policies,
        release_author_id=1,
    )

    assert "production-release environment must assign a reviewer independent of the release author" in errors


def test_main_fetches_the_environment_deployment_policy_and_writes_a_private_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    repository, protection, environment, secrets, deployment_policies = _valid_settings()
    repository["default_branch"] = "main"
    default_branch_commit = {"sha": "a" * 40}
    endpoints: list[str] = []

    def fake_api(endpoint: str) -> dict[str, Any]:
        endpoints.append(endpoint)
        values = {
            "repos/example/guildbridge": repository,
            "repos/example/guildbridge/commits/main": default_branch_commit,
            "user": {"id": 2},
            "repos/example/guildbridge/branches/main/protection": protection,
            "repos/example/guildbridge/environments/production-release": environment,
            "repos/example/guildbridge/environments/production-release/deployment-branch-policies": deployment_policies,
            "repos/example/guildbridge/environments/production-release/secrets": secrets,
        }
        return values[endpoint]

    monkeypatch.setattr(module.shutil, "which", lambda _name: "gh")
    monkeypatch.setattr(module, "_gh_api", fake_api)
    monkeypatch.setattr(
        module,
        "_gh_list",
        lambda endpoint: (
            _valid_tag_rulesets()
            if "rulesets" in endpoint
            else _valid_codeql_analyses()
            if "code-scanning/analyses" in endpoint
            else []
        ),
    )

    receipt_path = tmp_path / "github-production-settings-audit.json"
    assert module.main(["--repo", "example/guildbridge", "--receipt-out", str(receipt_path)]) == 0
    assert "user" in endpoints
    assert "repos/example/guildbridge/environments/production-release/deployment-branch-policies" in endpoints
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["schema"] == "guildbridge.github-production-settings-audit-receipt.v1"
    assert receipt["repository"] == "example/guildbridge"
    assert receipt["verified_controls"] == [
        "repository_security",
        "branch_protection",
        "release_tag_protection",
        "environment_protection",
        "environment_secret_names",
        "open_codeql_alerts",
        "codeql_freshness",
    ]


def test_main_does_not_write_a_receipt_when_hosted_controls_fail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    repository, protection, environment, secrets, deployment_policies = _valid_settings()
    protection["required_signatures"] = {"enabled": False}

    def fake_api(endpoint: str) -> dict[str, Any]:
        values = {
            "repos/example/guildbridge": repository,
            "repos/example/guildbridge/commits/main": {"sha": "a" * 40},
            "user": {"id": 2, "login": "release-owner"},
            "repos/example/guildbridge/branches/main/protection": protection,
            "repos/example/guildbridge/environments/production-release": environment,
            "repos/example/guildbridge/environments/production-release/deployment-branch-policies": deployment_policies,
            "repos/example/guildbridge/environments/production-release/secrets": secrets,
        }
        return values[endpoint]

    receipt_path = tmp_path / "github-production-settings-audit.json"
    monkeypatch.setattr(module.shutil, "which", lambda _name: "gh")
    monkeypatch.setattr(module, "_gh_api", fake_api)
    monkeypatch.setattr(
        module,
        "_gh_list",
        lambda endpoint: (
            _valid_tag_rulesets()
            if "rulesets" in endpoint
            else _valid_codeql_analyses()
            if "code-scanning/analyses" in endpoint
            else []
        ),
    )

    assert module.main(["--repo", "example/guildbridge", "--receipt-out", str(receipt_path)]) == 1
    assert not receipt_path.exists()


def test_main_prints_remediation_only_when_requested(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    module = _module()
    repository, protection, environment, secrets, deployment_policies = _valid_settings()
    protection["required_signatures"] = {"enabled": False}

    def fake_api(endpoint: str) -> dict[str, Any]:
        values = {
            "repos/example/guildbridge": {**repository, "default_branch": "main"},
            "repos/example/guildbridge/commits/main": {"sha": "a" * 40},
            "user": {"id": 2},
            "repos/example/guildbridge/branches/main/protection": protection,
            "repos/example/guildbridge/environments/production-release": environment,
            "repos/example/guildbridge/environments/production-release/deployment-branch-policies": deployment_policies,
            "repos/example/guildbridge/environments/production-release/secrets": secrets,
        }
        return values[endpoint]

    monkeypatch.setattr(module.shutil, "which", lambda _name: "gh")
    monkeypatch.setattr(module, "_gh_api", fake_api)
    monkeypatch.setattr(
        module,
        "_gh_list",
        lambda endpoint: _valid_tag_rulesets() if "rulesets" in endpoint else _valid_codeql_analyses() if "analyses" in endpoint else [],
    )

    assert module.main(["--repo", "example/guildbridge", "--remediation"]) == 1
    captured = capsys.readouterr()
    assert "Remediation:" in captured.err
    assert "signed commits" in captured.err
