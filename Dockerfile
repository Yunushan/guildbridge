FROM python:3.14.8-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170
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
