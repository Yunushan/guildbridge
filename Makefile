.PHONY: install dev test lint typecheck check clean

install:
	python -m pip install -e .

dev:
	python -m pip install -e .[dev]

test:
	pytest -q

lint:
	ruff check src tests

typecheck:
	mypy src

check: lint typecheck test

clean:
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
