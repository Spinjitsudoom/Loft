# 🎉 Loft 0.1.1 - Stable Release

**Release Date:** November 20, 2026  
**Status:** ✅ **PRODUCTION READY**

This is the first stable release of Loft, ready for deployment in production environments.

## Quick Start

```bash
# Install
pip install loft==0.1.1

# Run
loft

# Access at http://localhost:8000
```

## What's Included

- **Self-hosted ebook library** with paper-curl page reader
- **What's New popup** - Automatic changelog notifications on updates
- **Automatic update checking** - Monitors GitHub for new releases
- **Database backups** - Daily backups with rotation policy
- **Multi-user support** - Admin controls and user management
- **Advanced metadata** - Lookups from Google Books, OpenLibrary, ISBNdb, Hardcover, AniList
- **Rich format support** - EPUB, PDF, MOBI, AZW3, FB2, CBR/CBZ comics
- **Beautiful UI** - Cover wall, shelves, paper-curl reader
- **Offline support** - Service Worker for offline browsing
- **Multi-platform** - Runs on Linux, Windows, macOS, Docker

## Installation Methods

### 1. PyPI (Recommended for Servers)
```bash
pip install loft==0.1.1
loft  # Runs at localhost:8000
```

### 2. Docker
```bash
docker build -t loft:0.1.1 .
docker compose up -d
```

### 3. Linux Systemd
```bash
sudo cp deploy/loft.service /etc/systemd/system/
sudo systemctl enable loft
sudo systemctl start loft
```

### 4. Desktop/Mobile (Build from Source)
See [README.md](README.md) for build instructions for Windows, macOS, Linux, and Android.

## Security

- Read-only access to your book files
- Password-protected user accounts
- No tracking or telemetry
- Open source - audit the code
- AGPL-3.0 licensed

## Support

- 📖 [README.md](README.md) - Full documentation
- 📝 [CHANGELOG.md](CHANGELOG.md) - Release notes
- 🐛 [GitHub Issues](https://github.com/Spinjitsudoom/Loft/issues) - Bug reports
- 💬 [GitHub Discussions](https://github.com/Spinjitsudoom/Loft/discussions) - Questions & ideas

## License

AGPL-3.0-or-later - See [LICENSE](LICENSE) for details

---

**Ready to use. Enjoy your Loft! 📚**
