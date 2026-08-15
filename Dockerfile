FROM python:3.14.7-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4
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
