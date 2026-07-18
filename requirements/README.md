# Dependency Locks

## Linux container runtime lock

`runtime-linux.txt` is the hash-locked runtime closure for the pinned Python
3.14 Linux container image. It includes the Windows and Linux Keyring backend
dependencies because `pip-compile` evaluates environment markers on the host
that generates the file; keeping both backends in the closure makes the lock
portable and reproducible across the supported build hosts.

Do not edit `runtime-linux.txt` by hand. Regenerate it after changing the
runtime dependencies in `pyproject.toml` or `runtime.in`:

```text
make lock-runtime-linux
```

Validate it with the pinned Linux image before merging:

```text
python -m pip download --dest /tmp/guildbridge-wheelhouse --require-hashes --only-binary=:all: --platform manylinux_2_17_x86_64 --python-version 3.14 --implementation cp -r requirements/runtime-linux.txt
docker run --rm -v "$PWD:/src:ro" -v "/tmp/guildbridge-wheelhouse:/wheelhouse:ro" -w /src python:3.14.5-slim@sha256:c845af9399020c7e562969a13689e929074a10fd057acd1b1fad06a2fb068e97 python -m pip install --dry-run --no-index --find-links /wheelhouse --require-hashes -r requirements/runtime-linux.txt
```

## Release dependency lock

`release.txt` is the hash-locked dependency closure used by the GitHub release
jobs on Python 3.14. It includes the runtime dependencies, release tooling, and
Windows packaging tooling required to build a public release on both Ubuntu and
Windows runners.

Do not edit `release.txt` by hand. Regenerate it after changing `pyproject.toml`:

```text
make lock-release
```

Then validate it in a clean Python 3.14 environment:

```text
python -m pip install --require-hashes -r requirements/release.txt
python -m pip install --no-deps -e ".[dev,windows-build]"
```

The wider CI matrix intentionally resolves dependencies for each supported
Python version. That preserves compatibility coverage; the release lock
provides deterministic supply-chain inputs for public artifacts.
