# Loft Releases

## Stable Release

### [0.1.1] - 2026-11-20 ⭐ STABLE

**Production Ready** - Recommended for all users.

**Installation:**
```bash
pip install loft==0.1.1
```

**Features:**
- ✅ Full ebook library server
- ✅ What's New popup with changelog
- ✅ Automatic update checking
- ✅ Database backups with rotation
- ✅ Multi-user support with admin controls
- ✅ Paper-curl page-turning reader
- ✅ Support for EPUB, PDF, MOBI, AZW3, FB2, comics
- ✅ Beautiful cover-wall library view
- ✅ Advanced book metadata lookups
- ✅ Offline support with Service Worker
- ✅ Linux systemd integration
- ✅ Docker deployment ready

**Deployment Options:**
1. **Server**: `pip install loft==0.1.1`
2. **Docker**: Build from source with `docker build -t loft:0.1.1 .`
3. **Web UI**: Access via browser at `http://localhost:8000`

**Desktop & Mobile:**
Build from source:
- Windows: `cd desktop && npm install && npm run dist:win`
- macOS: `cd desktop && npm install && npm run dist:mac`
- Linux: `cd desktop && npm install && npm run dist:deb`
- Android: `cd android-lite && bash build.sh`

---

## Development Releases

### [0.2.0] - In Development

Multi-platform builds (Windows, macOS, Linux installers).
Status: Desktop builds working, Android coming soon.

---

## Upgrade Path

**From 0.1.0 → 0.1.1:**
- Automatic update checking will notify you
- Database backups preserve your library
- No data migration needed

**Installation:**
```bash
pip install --upgrade loft
```

---

For detailed changelog, see [CHANGELOG.md](CHANGELOG.md)
