.PHONY: install dev test lint typecheck platform-check gui web package check release-check clean

install:
	python -m pip install -e .

dev:
	python -m pip install -e ".[dev]"

test:
	python -m pytest -q

lint:
	python -m ruff check src tests scripts/check-platform.py scripts/verify-dist.py

typecheck:
	python -m mypy src

platform-check:
	python scripts/check-platform.py --require cli --format json

package:
	python -m build
	python -m twine check dist/*
	python scripts/verify-dist.py

gui:
	python -m guildbridge.gui

web:
	python -m guildbridge.web

check: lint typecheck test platform-check

release-check: check package

clean:
	python -c "import pathlib, shutil; [shutil.rmtree(path, ignore_errors=True) for path in ('build', 'dist', '.pytest_cache', '.mypy_cache', '.ruff_cache')]; [shutil.rmtree(path, ignore_errors=True) for path in pathlib.Path('.').glob('*.egg-info')]; [shutil.rmtree(path, ignore_errors=True) for path in pathlib.Path('.').rglob('__pycache__')]"
