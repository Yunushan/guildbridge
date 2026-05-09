from __future__ import annotations

APPLY_CONFIRMATION = "APPLY"


def validate_apply_safety(
    *,
    apply: bool,
    confirm_apply: str | None,
    validation_problems: list[str],
    force_invalid_template: bool = False,
) -> None:
    if not apply:
        return
    if (confirm_apply or "").strip() != APPLY_CONFIRMATION:
        raise ValueError(f"Refusing --apply without --confirm-apply {APPLY_CONFIRMATION}.")
    if validation_problems and not force_invalid_template:
        problem_text = "; ".join(validation_problems[:5])
        suffix = f" Problems: {problem_text}" if problem_text else ""
        raise ValueError(
            "Refusing --apply because the template failed validation. "
            "Fix the template or pass --force-invalid-template after reviewing the risk."
            f"{suffix}"
        )
