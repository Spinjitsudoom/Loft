# Alcove in a container, for PCs and servers (amd64) and Raspberry Pi and other ARM boards (arm64).
#
#   docker compose up -d        (see compose.yaml and docs/docker.md)
#
# Your books are read from /books. Alcove never changes a file that's there; books added in the app
# are saved into it as Author/Title/file, so mount it read-only only if you won't add any. Accounts, the library
# database, covers, page images and downloads' sources live in /data: mount a volume there.

FROM docker.io/library/python:3.14-slim

# unar opens CBR (RAR) comics; tini passes stop signals on; tzdata so TZ works.
RUN apt-get update \
 && apt-get install -y --no-install-recommends unar tini tzdata ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.9 /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/alcove \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable && rm -rf /root/.cache

COPY docker/config.toml /etc/alcove/config.toml
RUN mkdir -p /data /books && chown 1000:1000 /data

ENV PATH=/opt/alcove/bin:$PATH \
    ALCOVE_CONFIG=/etc/alcove/config.toml \
    ALCOVE_DATA_DIR=/data \
    ALCOVE_HOST=0.0.0.0 \
    ALCOVE_PORT=4545

# Not root. To match the owner of your books, run it as another user (compose: `user: "1000:1000"`).
USER 1000:1000
VOLUME /data
EXPOSE 4545
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4545/api/status', timeout=4)"
ENTRYPOINT ["tini", "--"]
CMD ["alcove"]
