# Loft in Docker

Loft runs in a container on ordinary PCs and servers (amd64) and on Raspberry Pi and other ARM
boards (arm64). It's the same server as a direct install, and the browser, phone and desktop apps
work with it the same way.

## Start it

Loft's image is `ghcr.io/spinjitsudoom/loft` (`latest`, or a version such as `0.1.7`). Take
`compose.yaml` (from this folder, or `loft-compose.yaml` from a
[release](https://github.com/Spinjitsudoom/Loft/releases/latest)), change the books path in it to
yours, then:

```bash
docker compose up -d
```

Open `http://<that computer's address>:4545`. The first person to open it makes the admin
account. Loft starts reading `/books` straight away and looks for new books every 10 minutes
(or at once with **Library settings → Rescan now**).

Without Compose:

```bash
docker run -d --name loft --restart unless-stopped -p 4545:4545 \
  -v ./loft-data:/data -v /path/to/your/books:/books -e TZ=Europe/Brussels \
  ghcr.io/spinjitsudoom/loft:latest
```

Podman works the same (`podman run`; add `--userns=keep-id` so files Loft saves belong to you). To
build the image yourself from this folder: `docker build -t loft .`, or `build: .` in `compose.yaml`.

## ZimaOS and CasaOS

1. Download `loft-zimaos.yaml` from the [latest release](https://github.com/Spinjitsudoom/Loft/releases/latest)
   (it's `docker/zimaos.yaml` here).
2. On the dashboard choose **+ → Install a customized app**, then **Import**, and upload or paste it.
3. Before installing, change the books folder (`/DATA/Media/Books`) to where your books are, and
   the time zone. Loft's own data goes in `/DATA/AppData/loft`.
4. Install, then open Loft from its tile.

To add books from Loft, the books folder must be writable by the user Loft runs as (`PUID` and
`PGID`, 1000). If ZimaOS's folders belong to root, set both to `0`.

## Your books, and who owns the files

- Loft only reads the books that are there. It never renames, moves or rewrites them.
- Books you **add in Loft** are saved into the books folder as `Author/Title/file`, so the
  folder needs to be writable for that. If you'll never add books in the app, mount it read-only
  (`/path/to/your/books:/books:ro`).
- Loft runs as user 1000, not as root. The books must be readable by it. It makes `loft-data` its
  own when it starts. If your books belong to someone else, set `PUID` and `PGID` in
  `compose.yaml` to their user and group numbers (from `id`).

**More than one books folder:** mount each under `/books` (for example `/books/comics`), then add
them in **Library settings → Books folders**.

## Settings

Most settings are in the app (Library settings). These environment variables override the file:

| Variable | What it does |
| --- | --- |
| `TZ` | Your time zone. |
| `LOFT_BOOKS_DIRS` | Fixed books folders, separated by `:`. |
| `LOFT_PORT` | The port inside the container (4545). |
| `FORWARDED_ALLOW_IPS` | Behind a reverse proxy or `tailscale serve`: set to `*` (or the proxy's address) so Loft sees https. |

## Away from home, and https

Loft isn't meant to be open to the internet. Use Tailscale, as with Shelf: install it on the
server and on your phone, tablet and laptop, and open `http://<server's Tailscale name>:4545`.

For **https** (which lets a phone keep the app itself for opening with no connection, not just
the downloaded books), have Tailscale serve it:

```bash
sudo tailscale serve --bg 4545
```

That gives `https://<server>.<tailnet>.ts.net` on every device signed in to your tailnet. Set
`FORWARDED_ALLOW_IPS: "*"` in `compose.yaml` when you do.

## Updating

```bash
docker compose pull && docker compose up -d
```

On ZimaOS and CasaOS, update Loft from its app settings (it pulls `latest` again). Loft tells
admins when a new version is out.

Everything you keep (accounts, the library, covers, settings) is in `loft-data`; back that up.
