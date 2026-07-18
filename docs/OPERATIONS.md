# Operations Runbook

This runbook is the minimum operating procedure for a production migration. It complements the generated journal; it does not make provider writes reversible.

## Before an apply

1. Use a dedicated least-privilege migration account and record its owner outside the repository.
2. Export and retain a sanitized source template, reviewed plan, and the target's pre-migration structure snapshot in approved private storage.
3. Run a disposable-tenant dry run for the exact provider route and record the operator, release tag, date, and outcome.
4. Define a change window, approver, incident owner, and the compensating action for each target provider before selecting **Actual Run**.

## During an apply

1. Keep the reviewed plan, journal output, and any provider audit-log reason together in private storage.
2. Stop on unexpected provider authorization, rate-limit, or validation failures. Do not retry with a changed plan.
3. Use `--resume-journal` only after the tool confirms the reviewed plan and action hash match the interrupted run.

## Recovery and retention

1. Treat the target snapshot and reviewed plan as the recovery baseline. Use a new, reviewed compensating plan; do not hand-edit a partially applied journal.
2. Retain journals and migration reports for the organization-approved audit period. Restrict access because they can reveal operational metadata even when provider credentials are excluded.
3. Rotate affected credentials and open a private security advisory if any token, session, private template, or journal is exposed.
4. Record the final outcome, recovery actions, and operator approval with the release evidence for the exact tag.
