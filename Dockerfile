FROM python:3.15.0-slim@sha256:f5b92f2a669a4c347044f29367f31983280b648250ca94dea66f98c53bc87e58
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY requirements/runtime-linux.txt ./requirements/runtime-linux.txt
COPY src ./src
RUN python -m pip install --no-cache-dir --require-hashes -r requirements/runtime-linux.txt \
    && python -m pip install --no-cache-dir --no-deps . \
    && addgroup --system guildbridge \
    && adduser --system --ingroup guildbridge --home /app guildbridge \
    && chown -R guildbridge:guildbridge /app
USER guildbridge
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 CMD guildbridge --version || exit 1
ENTRYPOINT ["guildbridge"]
