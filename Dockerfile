# litegm container image.
#
# Build:  docker build -t litegm .
# Run:    docker run -p 8080:8080 -v ./.config:/app/.config -v ./data:/app/data \
#           -e LITEGM_MASTER_KEY=... litegm
#
# The image ships the example configuration (``config/``) and its workflow
# templates; the real configuration is mounted from the host's ``.config/``
# directory and passed through ``--config`` (see docker-compose.yml).
#
# If Docker Hub is unreachable, pass registry mirrors per stage:
#   docker build --build-arg NODE_IMAGE=docker.m.daocloud.io/library/node:22-alpine \
#                --build-arg PIXI_IMAGE=docker.m.daocloud.io/prefix-dev/pixi:0.83.0 -t litegm .
#
# The admin UI is built in a Node stage and served by the gateway from /admin.
# The runtime environment is created by pixi from pixi.lock, so the container
# matches the local development environment exactly (Python 3.15 + conda-forge).

ARG NODE_IMAGE=node:22-alpine
ARG PIXI_IMAGE=ghcr.io/prefix-dev/pixi:0.83.0

FROM ${NODE_IMAGE} AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM ${PIXI_IMAGE} AS runtime
WORKDIR /app

# Create the environment from the committed lock file (default environment).
# ffmpeg/ffprobe are part of that environment (see pyproject.toml), so the admin
# console can extract video first frames and probe media without extra packages.
COPY pixi.lock pyproject.toml ./
COPY src/ ./src/
RUN pixi install --locked --environment default \
 && pixi run --environment default ffmpeg -version \
 && pixi run --environment default ffprobe -version

COPY config/ ./config/
COPY --from=web /web/dist ./web/dist

ENV PYTHONPATH=/app/src \
    LITEGM_CONFIG=/app/.config/litegm.yaml \
    LITEGM_BASE_DIR=/app \
    LITEGM_WEB_DIR=/app/web/dist \
    # ``pixi run`` at start-up needs writable caches; the base image defaults to
    # /.cache, which is not writable for the non-root runtime user.
    PIXI_CACHE_DIR=/app/.pixi-cache \
    RATTLER_CACHE_DIR=/app/.pixi-cache/rattler \
    UV_CACHE_DIR=/app/.pixi-cache/uv

RUN mkdir -p /app/data /app/.config /app/.pixi-cache && chown -R 10001:10001 /app

# Compose bind-mounts the host's ./data over /app/data, which hides the
# directory created above and inherits the host's ownership. A host directory
# owned by root (for example because it was created by an earlier docker run)
# then makes SQLite fail with "unable to open database file" as UID 10001. The
# entrypoint fixes ownership when it is allowed to (running as root) and then
# drops to 10001 before starting the gateway.
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh

USER 10001:10001

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s \
  CMD pixi run --environment default python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health/live', timeout=3).status==200 else 1)"

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["pixi", "run", "--environment", "default", "python", "-m", "litegm.cli", "serve", "--config", "/app/.config/litegm.yaml", "--base-dir", "/app"]