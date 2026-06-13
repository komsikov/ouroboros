ARG CI_BASE_IMAGE=registry.genai.int/ci/uv:python3.10-ouroboros-base-bookworm-slim
FROM ${CI_BASE_IMAGE}

RUN rm -rf /var/lib/apt/lists/*

# --- Runtime user / layout -------------------------------------------------
ARG APP_UID=1000
ARG APP_GID=1000
ARG APP_USER=app
ARG APP_HOME=/home/app

# The image code is baked into /opt/ouroboros_image. On first start the
# entrypoint seeds a writable runtime repo at /opt/ouroboros, runs the server
# from it (self-modification persists), and continuously bundles repo+data to
# the /mnt mount so state survives container restarts.
ENV HOME=${APP_HOME} \
    PATH=${APP_HOME}/.local/bin:${PATH} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OUROBOROS_REPO_DIR=/opt/ouroboros \
    OUROBOROS_DATA_DIR=/opt/ouroboros/data \
    OUROBOROS_SYNC_INTERVAL_SECONDS=30 \
    OUROBOROS_BUNDLE_ARCHIVE_NAME=ouroboros-bundle.zip

# System tooling required by the sync entrypoint (zip/unzip), git operations
# on the runtime repo, and general ops convenience.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git git-lfs vim curl wget rsync zip unzip && \
    rm -rf /var/lib/apt/lists/*

# Non-root runtime user (idempotent: the corporate base may already define it).
RUN if ! getent group ${APP_GID} >/dev/null 2>&1; then groupadd -g ${APP_GID} ${APP_USER}; fi && \
    if ! id -u ${APP_USER} >/dev/null 2>&1; then \
        useradd -m -d ${APP_HOME} -u ${APP_UID} -g ${APP_GID} -s /bin/bash ${APP_USER}; \
    fi

# --- Python dependencies ---------------------------------------------------
# Optional internal PyPI proxy (Nexus). When empty, pip falls back to public
# PyPI — useful for local builds outside the Nexus network.
ARG PIP_INDEX_URL=
ENV PIP_INDEX_URL=${PIP_INDEX_URL}

WORKDIR /opt/ouroboros_image
COPY requirements.txt .

# Install Python dependencies. If the build was invoked with the ``nexus_ca``
# secret (buildah --secret id=nexus_ca,src=...), import it into the system
# trust bundle so pip can verify the proxy's HTTPS chain in the same RUN.
RUN --mount=type=secret,id=nexus_ca,required=false \
    if [ -f /run/secrets/nexus_ca ]; then \
        cp /run/secrets/nexus_ca /usr/local/share/ca-certificates/nexus-ca.crt && \
        update-ca-certificates; \
    fi && \
    pip install --no-cache-dir -r requirements.txt

# Playwright Chromium browser + native system deps. Run as root, before the
# USER switch, because install-deps drives apt. PLAYWRIGHT_BROWSERS_PATH=0
# stores the browser alongside the package so the app user can read it.
RUN python3 -m playwright install-deps chromium
RUN PLAYWRIGHT_BROWSERS_PATH=0 python3 -m playwright install chromium

# --- Application code & runtime dirs ---------------------------------------
COPY --chown=${APP_UID}:${APP_GID} . /opt/ouroboros_image

# Persisted runtime repo, its data dir, and the /mnt bundle mount point.
RUN mkdir -p /opt/ouroboros /mnt && \
    chown -R ${APP_UID}:${APP_GID} /opt/ouroboros /mnt ${APP_HOME}

# Sync + entrypoint scripts.
COPY docker/entrypoint.sh /usr/local/bin/ouroboros-entrypoint
COPY docker/sync_dirs.sh /usr/local/bin/ouroboros-sync-dirs
RUN chmod 755 /usr/local/bin/ouroboros-entrypoint /usr/local/bin/ouroboros-sync-dirs

# --- Server runtime env ----------------------------------------------------
ENV OUROBOROS_SERVER_HOST=0.0.0.0 \
    OUROBOROS_SERVER_PORT=8765 \
    OUROBOROS_AUTO_GRANT_REVIEWED_SKILLS=1 \
    OUROBOROS_TRUST_NONLOCAL_BIND_WITHOUT_PASSWORD=1 \
    OUROBOROS_SKILLS_REPO_PATH=/opt/ouroboros/skills \
    OUROBOROS_FILE_BROWSER_DEFAULT=/opt/ouroboros

USER ${APP_USER}

EXPOSE 8765
ENTRYPOINT ["/usr/local/bin/ouroboros-entrypoint"]
