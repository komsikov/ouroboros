FROM registry.genai.int/ci/uv:python3.10-bookworm-slim

# System dependencies. ``build-essential`` is required because some
# transitive deps of nemoguardrails (annoy via fastembed) lack prebuilt
# wheels for linux/arm64. ``ca-certificates`` lets the optional Nexus CA
# build secret slot into the system trust bundle below.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    # build-essential \
    # ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Working directory
ENV APP_HOME=/app
WORKDIR ${APP_HOME}

# Optional internal PyPI proxy (Nexus). When empty, pip falls back to
# public PyPI — useful for local builds outside the Nexus network.
ARG PIP_INDEX_URL=
ENV PIP_INDEX_URL=${PIP_INDEX_URL}

# Install Python dependencies. If the build was invoked with the
# ``nexus_ca`` secret (buildah --secret id=nexus_ca,src=...), import it
# into the system trust bundle so pip can verify the proxy's HTTPS chain
# in the same RUN.
COPY requirements.txt .
RUN --mount=type=secret,id=nexus_ca,required=false \
    if [ -f /run/secrets/nexus_ca ]; then \
        cp /run/secrets/nexus_ca /usr/local/share/ca-certificates/nexus-ca.crt && \
        update-ca-certificates; \
    fi && \
    pip install --no-cache-dir -r requirements.txt

# Install all Playwright native system dependencies for Chromium (authoritative list from Playwright)
RUN python3 -m playwright install-deps chromium

# Install Playwright Chromium browser binary so browser tools work out of the box
RUN PLAYWRIGHT_BROWSERS_PATH=0 python3 -m playwright install chromium

# Copy application
COPY . .

# Default environment
ENV OUROBOROS_SERVER_HOST=0.0.0.0 \
    OUROBOROS_SERVER_PORT=8765 \
    OUROBOROS_FILE_BROWSER_DEFAULT=${APP_HOME} \
    OUROBOROS_AUTO_GRANT_REVIEWED_SKILLS=1 \
    OUROBOROS_TRUST_NONLOCAL_BIND_WITHOUT_PASSWORD=1

EXPOSE 8765

ENTRYPOINT ["python", "server.py"]
