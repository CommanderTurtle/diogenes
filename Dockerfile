# Bun is the image's only JavaScript runtime. Copy the versioned binary from
# the official multi-architecture image instead of installing Node/npm or
# piping an installer into a root shell.
FROM oven/bun:1.3.14 AS bun-runtime

# Both stages need the fixed native decoder, including curl in the builder and
# the native fetch/curl paths in the runtime. A cached Python base may predate
# the Debian fix. Bun bundles its own decoder, so this gate covers the distro
# libraries rather than a distribution-provided JavaScript runtime.
FROM python:3.14.9-slim AS brotli-base
COPY scripts/check_brotli.py /usr/local/bin/check-brotli.py
COPY scripts/check_ca_trust.py /usr/local/bin/check-ca-trust.py
# Check inherited trust before the first HTTPS package request, retaining Debian's
# signed archive verification. Refresh only the explicit native dependency.
RUN python /usr/local/bin/check-ca-trust.py --system \
    && sed -i 's|http://deb.debian.org/|https://deb.debian.org/|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends libbrotli1 \
    && python /usr/local/bin/check-brotli.py \
    && rm -rf /var/lib/apt/lists/*

# ---- builder: patch + build wheels for Real-ESRGAN's broken-on-3.14 deps ----
# basicsr/gfpgan/facexlib read their version via exec()+locals()['__version__'],
# which raises KeyError on Python 3.13+ (PEP 667). Build patched wheels here so
# the final image / Cookbook never has to compile the broken sdists. See
# docker/build-realesrgan-wheels.sh for the full rationale.
FROM brotli-base AS realesrgan-wheels
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY scripts/check_ca_trust.py /usr/local/bin/check-ca-trust.py
RUN python /usr/local/bin/check-ca-trust.py --system
COPY requirements-bootstrap.txt /tmp/requirements-bootstrap.txt
RUN python -m pip install --no-cache-dir --require-hashes --only-binary=:all: --no-deps -r /tmp/requirements-bootstrap.txt \
    && python /usr/local/bin/check-ca-trust.py --python
COPY docker/build-realesrgan-wheels.sh /usr/local/bin/build-realesrgan-wheels.sh
RUN bash /usr/local/bin/build-realesrgan-wheels.sh /wheels

FROM brotli-base

# System deps. tmux is required by Cookbook for background downloads/serves.
# openssh-client is required for Cookbook remote server tests, setup, probes,
# downloads, and serves from Docker installs.
# git/cmake are required when Cookbook builds llama.cpp on first llama.cpp
# launch inside Docker.
# No browser binary is bundled here: browsing runs through the configurable
# Camofox backend or an intentionally mounted ODYSSEUS_BROWSER_EXECUTABLE, so
# the image keeps a single JavaScript runtime instead of a second stack.
# fontconfig + Noto CJK provide real fallback glyphs for multilingual pages and
# for any mounted browser, which otherwise renders Chinese/Japanese/Korean
# labels as empty boxes.
# iproute2/iputils-ping/net-tools/dnsutils/nmap give Docker-hosted agents the
# basic network inspection toolkit expected by local LAN/debugging tasks.
# gosu lets the entrypoint drop privileges cleanly so signals still reach
# uvicorn directly (no extra shell layer like `su`/`sudo` would add).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    curl \
    ca-certificates \
    git \
    fontconfig \
    fonts-noto-cjk \
    tmux \
    openssh-client \
    iproute2 \
    iputils-ping \
    net-tools \
    dnsutils \
    nmap \
    gosu \
    libgl1 \
    libglib2.0-0t64 \
    libxcb1 \
    libmagic1 \
    && python /usr/local/bin/check-brotli.py \
    && rm -rf /var/lib/apt/lists/*

# Refresh both Python trust bundles before installing application dependencies.
# System roots also serve web fetches, webhooks, curl, and Bun's TLS client.
COPY scripts/check_ca_trust.py /usr/local/bin/check-ca-trust.py
RUN python /usr/local/bin/check-ca-trust.py --system
COPY requirements-bootstrap.txt /tmp/requirements-bootstrap.txt
RUN python -m pip install --no-cache-dir --require-hashes --only-binary=:all: --no-deps -r /tmp/requirements-bootstrap.txt \
    && python /usr/local/bin/check-ca-trust.py --python
ENV GRPC_DEFAULT_SSL_ROOTS_FILE_PATH=/etc/ssl/certs/ca-certificates.crt

# Browsers keep a separate root store. Distrust the compromised intermediate
# public keys explicitly, including cross-signs, without waiting for CRL
# updates; a mounted browser binary picks this policy up from the default path.
COPY docker/chromium-emudhra.json /etc/chromium/policies/managed/odysseus-emudhra.json

# libgl1/libglib2.0-0t64/libxcb1 are runtime shared libs (libGL.so.1,
# libglib-2.0/libgthread, libxcb.so.1) that opencv-python (cv2) loads. The
# slim base omits them, so the Cookbook "install realesrgan" path imports cv2
# and dies with `libxcb.so.1: cannot open shared object file` despite a clean
# pip install. Using full opencv-python (not -headless) because basicsr/gfpgan/
# facexlib/realesrgan all depend on the `opencv-python` distribution by name.
#
# libmagic1 is the shared lib (libmagic.so.1) that python-magic dlopens for
# content-based MIME sniffing in src/upload_handler.py. We install both here
# (libmagic1 + the python-magic wrapper, below) rather than in requirements.txt
# because python-magic resolves libmagic at import time: where the lib is
# absent the import can block or raise, so keeping it image-only avoids
# regressing pip/venv installs on hosts without libmagic. Debian always has the
# lib here, so the import is instant and detection actually works.

# Docker CLI (client only — daemon stays on the host via the
# /var/run/docker.sock mount). The Debian `docker.io` package ships
# dockerd but not the client binary on slim, so grab the static client
# tarball from download.docker.com instead.
# 29.9.2 includes Go 1.26.10's eMudhra intermediate-key distrust.
ARG DOCKER_CLI_VERSION=29.9.2
RUN ARCH="$(dpkg --print-architecture)" \
    && case "$ARCH" in \
         amd64) DARCH=x86_64 ;; \
         arm64) DARCH=aarch64 ;; \
         *) echo "unsupported arch $ARCH"; exit 1 ;; \
       esac \
    && curl -fsSL "https://download.docker.com/linux/static/stable/${DARCH}/docker-${DOCKER_CLI_VERSION}.tgz" \
       -o /tmp/docker.tgz \
    && tar -xzf /tmp/docker.tgz -C /tmp \
    && install -m 0755 /tmp/docker/docker /usr/local/bin/docker \
    && rm -rf /tmp/docker /tmp/docker.tgz

WORKDIR /app

# Install the pinned Bun runtime and image-local compatibility facades. The
# facade translates canonical node/npm/npx/pnpm/yarn/corepack invocations into
# Bun; none of those foreign runtimes or package managers are installed.
COPY --from=bun-runtime /usr/local/bin/bun /usr/local/bin/bun
COPY docker/bun-compat /usr/local/libexec/bun-compat
COPY docker/bunfig.toml /app/.bunfig.toml
RUN chmod 0755 /usr/local/bin/bun /usr/local/libexec/bun-compat \
    && for command in node npm npx pnpm yarn corepack; do \
         ln -s /usr/local/libexec/bun-compat "/usr/local/bin/${command}"; \
       done \
    && test "$(bun --version)" = "1.3.14" \
    && node --version \
    && npm --version \
    && npx --version

# Disable Bun crash-report uploads and Hugging Face ecosystem telemetry even
# when the image is launched without Compose. Bun's global package cache is a
# writable/persistable app-user path rather than a root-owned image layer.
ENV BUN_INSTALL=/app/.bun \
    BUN_INSTALL_BIN=/app/.bun/bin \
    BUN_INSTALL_GLOBAL_DIR=/app/.bun/install/global \
    BUN_INSTALL_CACHE_DIR=/app/.bun/install/cache \
    DO_NOT_TRACK=1 \
    HF_HUB_DISABLE_TELEMETRY=1

# Private browser automation wrapper used by the native `private_browser` tool.
# Bun resolves it from the npm registry, but installs it into an image-owned
# prefix: /app/.bun is a runtime bind mount, so a build-time global install
# there would be hidden the moment Compose mounts it. The tool still drives an
# intentionally mounted browser executable — this image bundles no browser.
RUN BUN_INSTALL=/opt/bun BUN_INSTALL_CACHE_DIR=/opt/bun/install/cache \
      bun install -g agent-browser@0.35.0 \
    && for binary in /opt/bun/bin/*; do \
         ln -s "$binary" "/usr/local/bin/${binary##*/}"; \
       done

# Install Python deps first (layer cache). Optional extras (PyMuPDF AGPL, etc.)
# are opt-in so the default image stays MIT-core; see requirements-optional.txt.
ARG INSTALL_OPTIONAL=false
COPY requirements.txt requirements-optional.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$INSTALL_OPTIONAL" = "true" ]; then pip install --no-cache-dir -r requirements-optional.txt; fi

# python-magic powers content-based MIME sniffing in src/upload_handler.py.
# Image-only (not in requirements.txt) because it needs the libmagic1 system
# lib installed above; see the apt note near the top of this stage.
RUN pip install --no-cache-dir python-magic==0.4.27

# Pre-install the patched basicsr/gfpgan/facexlib wheels built in the
# realesrgan-wheels stage (--no-deps keeps the image lean — torch & friends are
# pulled only when realesrgan is actually installed). With these dists already
# satisfied, the Cookbook's plain `pip install realesrgan` resolves them from
# wheels instead of rebuilding the sdists that fail on Python 3.14.
COPY --from=realesrgan-wheels /wheels/ /tmp/odysseus-wheels/
RUN pip install --no-cache-dir --no-deps /tmp/odysseus-wheels/*.whl \
    && rm -rf /tmp/odysseus-wheels

# Check gRPC's effective defaults after all Python dependencies are installed.
# The application minimum fixes its bundled roots; the checked override also
# keeps the effective Docker selection consistent with system trust.
RUN python /usr/local/bin/check-ca-trust.py --system --python --grpc \
    && python /usr/local/bin/check-brotli.py

# Copy app code
COPY . .
# Require the redistribution notices in the image build context.
COPY licenses/ ./licenses/
COPY THIRD_PARTY_PROVENANCE.json ACKNOWLEDGMENTS.md ./

# Create writable directories (mount volumes here for persistence)
RUN mkdir -p data logs services/cache/search /app/.bun

# Entrypoint that drops to PUID/PGID (default 1000:1000) and repairs
# ownership on the bind-mounted /app/data and /app/logs. Without this,
# the container runs as root and writes root-owned files into host
# bind mounts — any later non-root run (or a host user trying to
# update them) silently fails on EPERM, breaking skill extraction,
# prefs persistence, mail attachments, etc.
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 7000

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7000"]
