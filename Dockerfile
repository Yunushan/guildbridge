FROM python:3.14.5-slim@sha256:c845af9399020c7e562969a13689e929074a10fd057acd1b1fad06a2fb068e97
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
