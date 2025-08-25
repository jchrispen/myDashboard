# syntax=docker/dockerfile:1.7
FROM python:3.13.7-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ARG APP_DIR=/app
ARG CFG_DIR=/config
ARG LOCAL_CFG_FILE

ENV APP_DIR="${APP_DIR}"
ENV CFG_DIR="${CFG_DIR}"

# Fail fast if not set
RUN test -n "${LOCAL_CFG_FILE}" || (echo "ERROR: LOCAL_CFG_FILE build-arg is required" && false)

# System deps: git + tini
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git tini && \
    rm -rf /var/lib/apt/lists/*

WORKDIR "${APP_DIR}"

# Initial clone so we can install deps at build time
RUN git clone --branch dev --single-branch https://github.com/jchrispen/myDashboard.git . \
 && mkdir -p "${CFG_DIR}"

# Runtime config from build context
# NOTE: LOCAL_CFG_FILE must be relative to the build context
COPY "${LOCAL_CFG_FILE}" "${CFG_DIR}/dashboard_config.json"

# Python deps (baked in)
RUN pip install --upgrade pip wheel setuptools \
 && pip install --no-cache-dir -r requirements.txt

# Add non-root user and fix ownership (so git works at runtime)
RUN useradd -m -u 10001 appuser \
 && chown -R appuser:appuser "${APP_DIR}" "${CFG_DIR}"

# Install entrypoint while still root
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Now drop privileges
USER appuser

ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["/usr/local/bin/docker-entrypoint.sh"]
