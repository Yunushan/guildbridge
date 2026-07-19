FROM python:3.14.6-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6
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
