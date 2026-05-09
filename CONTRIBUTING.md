# Contributing to GuildBridge

Thanks for helping improve GuildBridge.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
make check
```

## Design rules

1. Keep the neutral schema privacy-safe.
2. Do not add members, messages, DMs, profile fields, tokens, or session data to exported templates.
3. Put provider-specific API behavior inside `src/guildbridge/providers/`.
4. Keep permission mappings in `src/guildbridge/permissions.py` so community maintainers can patch them easily.
5. Always make writes opt-in with `--apply --confirm-apply APPLY --plan-in <reviewed-plan.json>`; dry-run must remain the default.

## Adding a provider

1. Create `src/guildbridge/providers/<provider>.py`.
2. Implement `export_template()` and `import_template()` from `Provider`.
3. Register it in `src/guildbridge/providers/__init__.py`.
4. Add examples to README.
5. Add tests that verify dry-run plans and privacy behavior.
6. Extend `tests/test_provider_contracts.py` so dry-runs stay write-free, apply actions match provider writes, and apply journals record every write.

## Pull request checklist

- [ ] `python -m ruff check src tests scripts/check-platform.py scripts/verify-dist.py`
- [ ] `python -m mypy src`
- [ ] `python -m pytest -q`
- [ ] `python scripts/check-platform.py --require cli --format json`
- [ ] `python -m build && python -m twine check dist/* && python scripts/verify-dist.py`
- [ ] no secrets in commits
- [ ] no private user data in fixtures
- [ ] README updated if CLI/provider behavior changed
