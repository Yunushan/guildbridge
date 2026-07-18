"""Verify GitHub-hosted controls required for a GuildBridge production release.

This is intentionally a manual, read-only gate. GitHub Actions' ``GITHUB_TOKEN``
does not normally have repository-administration rights, so checking these hosted
settings in the release job would create a misleading, privilege-heavy workflow.
Run it with an administrator-authenticated GitHub CLI before creating a public tag.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_CHECKS = {"package", "Analyze (python)", "Analyze (actions)"}
REQUIRED_ENVIRONMENT_RULES = {"branch_policy", "required_reviewers"}
REQUIRED_CODEQL_CATEGORIES = {"/language:python", "/language:actions"}
REQUIRED_RELEASE_TAG_RULE_TYPES = {"creation", "update", "deletion"}
REQUIRED_RELEASE_TAG_REF_PATTERN = "refs/tags/v*"
DEFAULT_RELEASE_TAG_PATTERN = "v*"
DEFAULT_RELEASE_SECRETS = (
    "GUILDBRIDGE_CODESIGN_PFX_BASE64",
    "GUILDBRIDGE_CODESIGN_PFX_PASSWORD",
    "GUILDBRIDGE_PRODUCTION_EVIDENCE_JSON",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify GitHub production repository settings without changing them.")
    parser.add_argument("--repo", required=True, help="GitHub repository in OWNER/REPOSITORY form")
    parser.add_argument("--environment", default="production-release", help="protected production environment name")
    parser.add_argument(
        "--release-author",
        help="GitHub login expected to create the release tag; defaults to the authenticated GitHub CLI user",
    )
    parser.add_argument(
        "--required-release-tag-pattern",
        default=DEFAULT_RELEASE_TAG_PATTERN,
        help="environment deployment policy required for public release tags (default: v*)",
    )
    parser.add_argument(
        "--require-release-secret",
        action="append",
        default=list(DEFAULT_RELEASE_SECRETS),
        help="environment secret name that must exist; may be repeated",
    )
    parser.add_argument(
        "--receipt-out",
        type=Path,
        help="optional private JSON receipt written only after a successful audit; never commit it",
    )
    parser.add_argument(
        "--overwrite-receipt",
        action="store_true",
        help="replace an existing --receipt-out file",
    )
    parser.add_argument(
        "--remediation",
        action="store_true",
        help="print ordered, credential-free remediation steps when hosted controls are incomplete",
    )
    args = parser.parse_args(argv)

    if not _valid_repo(args.repo):
        parser.error("--repo must be in OWNER/REPOSITORY form")
    if args.release_author is not None and not _valid_login(args.release_author):
        parser.error("--release-author must be a valid GitHub login")
    if not shutil.which("gh"):
        print("check-github-production-settings: error: GitHub CLI 'gh' is not installed or not on PATH.", file=sys.stderr)
        return 1

    try:
        repository = _gh_api(f"repos/{args.repo}")
        author = _gh_api(f"users/{args.release_author}" if args.release_author else "user")
        author_id = _integer(author.get("id"))
        if author_id < 1:
            raise RuntimeError("could not determine the release author GitHub account ID")
        default_branch = _string(repository.get("default_branch")) or "main"
        default_branch_commit = _gh_api(f"repos/{args.repo}/commits/{default_branch}")
        protection = _gh_api(f"repos/{args.repo}/branches/{default_branch}/protection")
        environment = _gh_api(f"repos/{args.repo}/environments/{args.environment}")
        deployment_policies = _gh_api(
            f"repos/{args.repo}/environments/{args.environment}/deployment-branch-policies"
        )
        secrets = _gh_api(f"repos/{args.repo}/environments/{args.environment}/secrets")
        rulesets = _gh_list(f"repos/{args.repo}/rulesets?includes_parents=true")
        open_codeql_alerts = _gh_list(f"repos/{args.repo}/code-scanning/alerts?state=open&per_page=100")
        codeql_analyses = _gh_list(
            f"repos/{args.repo}/code-scanning/analyses?ref=refs/heads/{default_branch}&per_page=100"
        )
    except RuntimeError as exc:
        print(f"check-github-production-settings: error: {exc}", file=sys.stderr)
        return 1

    errors = validate_settings(
        repository,
        protection,
        environment,
        secrets,
        deployment_policies=deployment_policies,
        rulesets=rulesets,
        open_codeql_alerts=open_codeql_alerts,
        default_branch_commit_sha=_string(default_branch_commit.get("sha")),
        codeql_analyses=codeql_analyses,
        required_secrets=args.require_release_secret,
        required_release_tag_pattern=args.required_release_tag_pattern,
        release_author_id=author_id,
        environment_name=args.environment,
    )
    if errors:
        print("check-github-production-settings: error:", file=sys.stderr)
        for index, error in enumerate(errors, start=1):
            print(f"- {_error_category(error)} (requirement {index})", file=sys.stderr)
        if args.remediation:
            print("Remediation:", file=sys.stderr)
            for index, step in enumerate(remediation_steps(errors, environment_name=args.environment), start=1):
                print(f"{index}. {step}", file=sys.stderr)
        return 1
    if args.receipt_out is not None:
        receipt = build_receipt(
            repo=args.repo,
            environment=args.environment,
            default_branch=default_branch,
            release_author=_string(author.get("login")) or args.release_author or "authenticated-gh-user",
            required_release_tag_pattern=args.required_release_tag_pattern,
            required_secrets=args.require_release_secret,
        )
        try:
            write_receipt(args.receipt_out, receipt, overwrite=args.overwrite_receipt)
        except OSError as exc:
            print(f"check-github-production-settings: error: could not write audit receipt: {exc}", file=sys.stderr)
            return 1
        print(f"Wrote private GitHub settings audit receipt to {args.receipt_out}.")
    print(f"GitHub production settings are verified for {args.repo} ({args.environment}).")
    return 0


def build_receipt(
    *,
    repo: str,
    environment: str,
    default_branch: str,
    release_author: str,
    required_release_tag_pattern: str,
    required_secrets: Iterable[str],
) -> dict[str, object]:
    """Create a credential-free record of a successful live hosted-controls audit."""
    return {
        "schema": "guildbridge.github-production-settings-audit-receipt.v1",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "repository": repo,
        "environment": environment,
        "default_branch": default_branch,
        "release_author": release_author,
        "required_release_tag_pattern": required_release_tag_pattern,
        "required_environment_secret_names": sorted(set(required_secrets)),
        "verified_controls": [
            "repository_security",
            "branch_protection",
            "release_tag_protection",
            "environment_protection",
            "environment_secret_names",
            "open_codeql_alerts",
            "codeql_freshness",
        ],
    }


def write_receipt(path: Path, receipt: dict[str, object], *, overwrite: bool) -> None:
    """Atomically write a private audit receipt without serializing fetched settings or secrets."""
    if path.exists() and not overwrite:
        raise OSError(f"{path} already exists; use --overwrite-receipt to replace it")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_settings(
    repository: dict[str, Any],
    protection: dict[str, Any],
    environment: dict[str, Any],
    secrets: dict[str, Any],
    *,
    deployment_policies: dict[str, Any] | None = None,
    rulesets: Iterable[dict[str, Any]] = (),
    open_codeql_alerts: Iterable[dict[str, Any]] = (),
    default_branch_commit_sha: str | None = None,
    codeql_analyses: Iterable[dict[str, Any]] = (),
    required_secrets: Iterable[str] = DEFAULT_RELEASE_SECRETS,
    required_release_tag_pattern: str = DEFAULT_RELEASE_TAG_PATTERN,
    release_author_id: int | None = None,
    environment_name: str = "production-release",
) -> list[str]:
    """Return policy failures without exposing any secret values."""
    errors: list[str] = []
    security = _mapping(repository.get("security_and_analysis"))
    for key in ("dependabot_security_updates", "secret_scanning", "secret_scanning_push_protection"):
        if _mapping(security.get(key)).get("status") != "enabled":
            errors.append(f"repository security_and_analysis.{key} must be enabled")

    required_checks = _mapping(protection.get("required_status_checks"))
    found_checks = set(_strings(required_checks.get("contexts")))
    missing_checks = sorted(REQUIRED_CHECKS - found_checks)
    if missing_checks:
        errors.append("main branch is missing required checks: " + ", ".join(missing_checks))
    if required_checks.get("strict") is not True:
        errors.append("main branch must require branches to be up to date before merging")

    reviews = _mapping(protection.get("required_pull_request_reviews"))
    if _integer(reviews.get("required_approving_review_count")) < 1:
        errors.append("main branch must require at least one approving pull-request review")
    if reviews.get("require_last_push_approval") is not True:
        errors.append("main branch must require approval after the latest push")
    if _mapping(protection.get("required_signatures")).get("enabled") is not True:
        errors.append("main branch must require verified or signed commits")
    if _mapping(protection.get("enforce_admins")).get("enabled") is not True:
        errors.append("main branch protection must apply to administrators")
    if _mapping(protection.get("required_linear_history")).get("enabled") is not True:
        errors.append("main branch must require linear history")
    if _mapping(protection.get("allow_force_pushes")).get("enabled") is not False:
        errors.append("main branch must not allow force pushes")
    if _mapping(protection.get("allow_deletions")).get("enabled") is not False:
        errors.append("main branch must not allow deletion")
    if protection.get("required_conversation_resolution") is not True:
        errors.append("main branch must require resolved review conversations")

    _validate_release_tag_protection(rulesets, errors)

    if environment.get("can_admins_bypass") is not False:
        errors.append(f"{environment_name} environment must not allow administrator bypass")
    rule_types = {rule.get("type") for rule in _mappings(environment.get("protection_rules"))}
    missing_rules = sorted(REQUIRED_ENVIRONMENT_RULES - rule_types)
    if missing_rules:
        errors.append(f"{environment_name} environment is missing protection rules: " + ", ".join(missing_rules))
    reviewer_rules = [
        rule for rule in _mappings(environment.get("protection_rules")) if rule.get("type") == "required_reviewers"
    ]
    reviewers = [
        reviewer
        for rule in reviewer_rules
        for reviewer in _mappings(rule.get("reviewers"))
    ]
    if reviewer_rules and not reviewers:
        errors.append(f"{environment_name} environment must assign at least one required reviewer")
    if release_author_id is not None and reviewers and _reviewers_are_only_author(reviewers, release_author_id):
        errors.append(
            f"{environment_name} environment must assign a reviewer independent of the release author"
        )
    deployment_policy = _mapping(environment.get("deployment_branch_policy"))
    if deployment_policy.get("custom_branch_policies") is not True:
        errors.append(f"{environment_name} environment must use custom protected tag policies")
    policy_names = {
        name
        for policy in _mappings(_mapping(deployment_policies).get("branch_policies"))
        if (name := _string(policy.get("name")))
    }
    if required_release_tag_pattern not in policy_names:
        errors.append(
            f"{environment_name} environment must include the protected release tag policy: "
            f"{required_release_tag_pattern}"
        )

    found_secrets = {item.get("name") for item in _mappings(secrets.get("secrets"))}
    missing_secrets = sorted(set(required_secrets) - found_secrets)
    if missing_secrets:
        errors.append(f"{environment_name} environment is missing required secret names: " + ", ".join(missing_secrets))
    alert_numbers = sorted(alert["number"] for alert in open_codeql_alerts if isinstance(alert.get("number"), int))
    if alert_numbers:
        errors.append("repository has open CodeQL alerts: " + ", ".join(map(str, alert_numbers)))
    _validate_codeql_freshness(default_branch_commit_sha, codeql_analyses, errors)
    return errors


def _validate_codeql_freshness(
    default_branch_commit_sha: str | None,
    analyses: Iterable[dict[str, Any]],
    errors: list[str],
) -> None:
    """Require current-commit CodeQL results for both checked workflow languages."""
    if not default_branch_commit_sha:
        errors.append("could not determine the current default-branch commit for CodeQL freshness")
        return
    completed_categories = {
        _string(analysis.get("category"))
        for analysis in analyses
        if _string(_mapping(analysis.get("tool")).get("name")) == "CodeQL"
        and _string(analysis.get("commit_sha")) == default_branch_commit_sha
    }
    missing_categories = sorted(REQUIRED_CODEQL_CATEGORIES - completed_categories)
    if missing_categories:
        errors.append(
            "current default-branch commit is missing CodeQL analyses: " + ", ".join(missing_categories)
        )


def _validate_release_tag_protection(rulesets: Iterable[dict[str, Any]], errors: list[str]) -> None:
    """Require immutable, restricted GitHub ruleset controls for public release tags."""
    matching_rulesets = [
        ruleset
        for ruleset in rulesets
        if ruleset.get("target") == "tag"
        and ruleset.get("enforcement") == "active"
        and REQUIRED_RELEASE_TAG_REF_PATTERN
        in _strings(_mapping(_mapping(ruleset.get("conditions")).get("ref_name")).get("include"))
    ]
    if not matching_rulesets:
        errors.append(
            "repository must have an active tag ruleset for refs/tags/v* that restricts creation, updates, and deletion"
        )
        return
    supported_rules = {
        _string(rule.get("type"))
        for ruleset in matching_rulesets
        for rule in _mappings(ruleset.get("rules"))
    }
    missing_rules = sorted(REQUIRED_RELEASE_TAG_RULE_TYPES - supported_rules)
    if missing_rules:
        errors.append(
            "release tag ruleset for refs/tags/v* is missing protections: " + ", ".join(missing_rules)
        )


def _error_category(error: str) -> str:
    """Return a stable, non-sensitive category for hosted audit diagnostics."""
    if error.startswith("repository security"):
        return "repository security control"
    if error.startswith("main branch"):
        return "branch protection control"
    if error.startswith("release tag ruleset") or error.startswith("repository must have an active tag ruleset"):
        return "release tag protection control"
    if error.startswith("current default-branch") or error.startswith("could not determine the current default-branch"):
        return "CodeQL freshness control"
    if error.startswith("repository has open CodeQL alerts"):
        return "open CodeQL alert control"
    return "production environment control"


def remediation_steps(errors: Iterable[str], *, environment_name: str) -> list[str]:
    """Return ordered, non-secret corrective actions for hosted-control failures."""
    findings = list(errors)
    steps: list[str] = []
    if any(error.startswith("repository security") for error in findings):
        steps.append(
            "Enable Dependabot security updates, secret scanning, and secret-scanning push protection in the repository security settings."
        )
    if any(error.startswith("main branch") for error in findings):
        steps.append(
            "Update main branch protection to require current branches, one approving review, last-push approval, signed commits, "
            "linear history, resolved conversations, and the package plus both CodeQL checks."
        )
    if any(
        error.startswith("release tag ruleset")
        or error.startswith("repository must have an active tag ruleset")
        for error in findings
    ):
        steps.append(
            "Create an active tag ruleset for refs/tags/v* that restricts creation, updates, and deletion to the authorized release identity."
        )
    environment_prefix = f"{environment_name} environment"
    if any(error.startswith(environment_prefix) for error in findings):
        steps.append(
            f"Configure the {environment_name} environment with a v* protected-tag policy, administrator-bypass disabled, and an independent required reviewer."
        )
        if any("required secret names" in error for error in findings):
            steps.append(
                f"Add the required signing and evidence secret values to {environment_name} in GitHub; do not place them in source control or command history."
            )
    if any(error.startswith("repository has open CodeQL alerts") for error in findings):
        steps.append(
            "Resolve the open CodeQL alerts through reviewed fixes, then wait for fresh Python and Actions analyses on main."
        )
    if any(
        error.startswith("current default-branch commit is missing CodeQL analyses")
        or error.startswith("could not determine the current default-branch")
        for error in findings
    ):
        steps.append("Wait for fresh Python and Actions CodeQL analyses for the current main commit, then rerun this audit.")
    return steps


def _gh_api(endpoint: str) -> dict[str, Any]:
    payload = _gh_json(endpoint)
    if not isinstance(payload, dict):
        raise RuntimeError(f"gh api {endpoint} returned an unexpected JSON shape")
    return payload


def _gh_list(endpoint: str) -> list[dict[str, Any]]:
    payload = _gh_json(endpoint)
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise RuntimeError(f"gh api {endpoint} returned an unexpected JSON shape")
    return payload


def _gh_json(endpoint: str) -> Any:
    # The command is an argument vector; endpoint comes from fixed, validated API paths.
    completed = subprocess.run(["gh", "api", endpoint], capture_output=True, text=True, check=False)  # noqa: S603, S607
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"gh api {endpoint} failed"
        raise RuntimeError(detail)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"gh api {endpoint} did not return JSON: {exc.msg}") from exc
    return payload


def _valid_repo(value: str) -> bool:
    owner, separator, name = value.partition("/")
    return bool(owner and separator and name and "/" not in name)


def _valid_login(value: str) -> bool:
    return bool(value) and all(character.isalnum() or character == "-" for character in value)


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _mappings(value: object) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _integer(value: object) -> int:
    return value if isinstance(value, int) else 0


def _string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _reviewers_are_only_author(reviewers: Iterable[dict[str, Any]], author_id: int) -> bool:
    """Detect the unambiguously unsafe case; team membership needs human review."""
    reviewer_ids = {
        _integer(_mapping(reviewer.get("reviewer")).get("id"))
        for reviewer in reviewers
        if reviewer.get("type") == "User"
    }
    has_team_reviewer = any(reviewer.get("type") == "Team" for reviewer in reviewers)
    return not has_team_reviewer and reviewer_ids == {author_id}


if __name__ == "__main__":
    raise SystemExit(main())
