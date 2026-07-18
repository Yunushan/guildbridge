.PHONY: install dev release-install runtime-install lock-runtime-linux lock-release test coverage lint security-lint exception-lint typecheck audit platform-check content-capability-scope release-controls secret-hygiene security-baseline gui web package check release-check clean clean-dist

install:
	python -m pip install -e .

dev:
	python -m pip install -e ".[dev]"

release-install:
	python -m pip install --require-hashes -r requirements/release.txt
	python -m pip install --no-deps -e ".[dev,windows-build]"

runtime-install:
	python -m pip install --require-hashes -r requirements/runtime-linux.txt
	python -m pip install --no-deps -e .

lock-runtime-linux:
	python -m piptools compile --strip-extras --generate-hashes --output-file requirements/runtime-linux.txt --pip-args "--platform manylinux_2_17_x86_64 --python-version 3.14 --implementation cp --only-binary=:all:" requirements/runtime.in

lock-release:
	python -m piptools compile --allow-unsafe --strip-extras --extra dev --extra windows-build --generate-hashes --output-file requirements/release.txt pyproject.toml

test:
	python -m pytest -q

coverage:
	python -m coverage run -m pytest -q
	python -m coverage report

lint:
	python -m ruff check src tests scripts/check-platform.py scripts/verify-dist.py scripts/check-release-version.py scripts/check-release-controls.py scripts/check-secret-hygiene.py scripts/check-security-baseline.py scripts/new-production-evidence-template.py scripts/check-github-production-settings.py scripts/check-production-evidence.py scripts/check-production-readiness.py scripts/record-provider-drill-receipt.py scripts/check-release-assets.py scripts/check-content-capability-scope.py scripts/pip-audit-truststore.py

security-lint:
	python -m ruff check --select S src scripts

exception-lint:
	python -m ruff check --select BLE src scripts

typecheck:
	python -m mypy src

audit:
	python scripts/pip-audit-truststore.py --strict

platform-check:
	python scripts/check-platform.py --require cli --format json

content-capability-scope:
	python scripts/check-content-capability-scope.py

release-controls:
	python scripts/check-release-controls.py

secret-hygiene:
	python scripts/check-secret-hygiene.py --history

security-baseline:
	python scripts/check-security-baseline.py

package: clean-dist
	python -m build
	python -m twine check dist/*.whl dist/*.tar.gz
	python scripts/verify-dist.py

gui:
	python -m guildbridge.gui

web:
	python -m guildbridge.web

check: lint security-lint exception-lint typecheck audit coverage platform-check content-capability-scope release-controls secret-hygiene security-baseline

release-check: check package

clean:
	python -c "import pathlib, shutil; [shutil.rmtree(path, ignore_errors=True) for path in ('build', 'dist', '.pytest_cache', '.mypy_cache', '.ruff_cache')]; [shutil.rmtree(path, ignore_errors=True) for path in pathlib.Path('.').glob('*.egg-info')]; [shutil.rmtree(path, ignore_errors=True) for path in pathlib.Path('.').rglob('__pycache__')]"

clean-dist:
	python -c "import pathlib, shutil; [shutil.rmtree(path, ignore_errors=True) for path in ('build', 'dist')]; [shutil.rmtree(path, ignore_errors=True) for path in pathlib.Path('.').glob('*.egg-info')]"
