FROM python:3.11.9-slim-bookworm@sha256:8fb099199b9f2d70342674bd9dbccd3ed03a258f26bbd1d556822c6dfc60c317

ARG UV_VERSION=0.11.16

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:${PATH}" \
    PROSTATE_JOURNEY_APP_CONFIG=/app/configs/application.yaml \
    PROSTATE_JOURNEY_ENVIRONMENT=local \
    PROSTATE_JOURNEY_HOST=0.0.0.0 \
    PROSTATE_JOURNEY_PORT=8080 \
    PROSTATE_JOURNEY_LOG_FORMAT=json \
    PROSTATE_JOURNEY_RELEASE_ROOT=/app/data/releases \
    PROSTATE_JOURNEY_PRESENTATION_ROOT=/app/outputs/presentation \
    PROSTATE_JOURNEY_TEMP_ROOT=/tmp/prostate-journey \
    PROSTATE_JOURNEY_EXPERIMENT_ROOT=/app/outputs/experiments

WORKDIR /app

RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}" \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

COPY pyproject.toml uv.lock README.md .python-version ./
COPY src ./src
COPY configs ./configs
COPY contracts ./contracts

RUN uv sync --frozen --no-dev --no-editable \
    && mkdir -p /app/data/releases /app/outputs/presentation /app/outputs/experiments /tmp/prostate-journey \
    && chown -R app:app /app /opt/venv /tmp/prostate-journey

USER 10001:10001

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3).read()"

CMD ["prostate-journey", "serve"]
