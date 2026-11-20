# Changelog

All notable changes to Loft will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-11-20

### Added
- **What's New popup** - Automatically shows release notes on first visit after update
- **GitHub Actions CI/CD** - Automated cross-platform builds for Windows, macOS, Linux, Android, and Docker
- **Automatic update checking** - App checks GitHub releases every hour for new versions
- **Database backups** - Automatic daily backups with rotation policy (keeps 7 latest)
- **Backup management API** - Create, list, and restore database backups
- Version tracking in localStorage for update detection

### Improved
- Release infrastructure with GitHub Actions workflows
- PyPI package publishing automation
- Docker image auto-build and push to GitHub Container Registry

## [0.1.0] - 2026-11-16

### Added
- Initial release of Loft
- Self-hosted ebook library with paper-curl page-turning reader
- Support for EPUB, PDF, MOBI, AZW3, FB2 formats
- Comic archive support (CBR, CBZ, CB7)
- Multi-user library with admin controls
- Cover wall library view with customizable shelves
- Advanced book metadata with lookups from:
  - Google Books
  - OpenLibrary
  - ISBNdb
  - Hardcover.app
  - AniList
- Beautiful responsive web UI
- Offline support with Service Worker
- Desktop apps (Electron) for Windows, macOS, Linux
- Android Lite client (web wrapper)
- Docker deployment support
- Linux systemd service integration
- Book requests and approvals system
- Library discussions and book clubs
- Advanced search and filtering
- Automatic book cover downloads
