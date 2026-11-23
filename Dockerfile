# Loft in a container, for PCs and servers (amd64) and Raspberry Pi and other ARM boards (arm64).
#
#   docker compose up -d        (see compose.yaml and docs/docker.md)
#
# Your books are read from /books. Loft never changes a file that's there; books added in the app
# are saved into it as Author/Title/file, so mount it read-only only if you won't add any. Accounts, the library
# database, covers, page images and downloads' sources live in /data: mount a volume there.

FROM docker.io/library/python:3.14-slim

# unar opens CBR (RAR) comics; tini passes stop signals on; tzdata so TZ works.
RUN apt-get update \
 && apt-get install -y --no-install-recommends unar tini tzdata ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.9 /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/loft \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable && rm -rf /root/.cache

COPY docker/config.toml /etc/loft/config.toml
COPY --chmod=755 docker/entrypoint.sh /usr/local/bin/loft-entrypoint
RUN mkdir -p /data /books && chown 1000:1000 /data

ENV PATH=/opt/loft/bin:$PATH \
    LOFT_CONFIG=/etc/loft/config.toml \
    LOFT_DATA_DIR=/data \
    LOFT_HOST=0.0.0.0 \
    LOFT_PORT=4545

# Loft itself never runs as root: the entrypoint gives it /data and runs it as PUID:PGID (1000:1000
# unless set; set them to the owner of your books). Started as another user (compose `user:`), it
# runs as that user instead.
ENV PUID=1000 PGID=1000
LABEL org.opencontainers.image.source="https://github.com/Spinjitsudoom/Loft" \
      org.opencontainers.image.title="Loft" \
      org.opencontainers.image.description="Your own ebook and comic library, read in the browser" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"
VOLUME /data
EXPOSE 4545
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4545/api/status', timeout=4)"
ENTRYPOINT ["tini", "--", "loft-entrypoint"]
CMD ["loft"]
