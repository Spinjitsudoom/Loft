"""Database backup management for Loft.

Automatic and manual database backups with rotation policy.
"""

from __future__ import annotations

import gzip
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


class BackupManager:
    """Manages database backups with automatic rotation."""

    def __init__(self, data_dir: Path, db_path: Path, backup_count: int = 7):
        """Initialize backup manager.
        
        Args:
            data_dir: Directory to store backups
            db_path: Path to the database file to backup
            backup_count: Number of backups to keep (older ones are deleted)
        """
        self.data_dir = data_dir
        self.db_path = db_path
        self.backup_count = backup_count
        self.backup_dir = data_dir / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def backup_now(self) -> Optional[Path]:
        """Create an immediate backup of the database.
        
        Returns:
            Path to the backup file, or None if backup failed
        """
        if not self.db_path.exists():
            log.warning(f"Database not found: {self.db_path}")
            return None

        try:
            # Create timestamped backup filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = self.backup_dir / f"loft_db_{timestamp}.sqlite.gz"

            # Compress database
            with open(self.db_path, "rb") as f_in:
                with gzip.open(backup_file, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)

            log.info(f"Backup created: {backup_file}")

            # Rotate old backups
            self._rotate_backups()

            return backup_file

        except Exception as e:
            log.error(f"Backup failed: {e}")
            return None

    def restore_backup(self, backup_file: Path) -> bool:
        """Restore database from a backup file.
        
        Args:
            backup_file: Path to the backup file (.sqlite.gz)
            
        Returns:
            True if restore succeeded, False otherwise
        """
        if not backup_file.exists():
            log.error(f"Backup file not found: {backup_file}")
            return False

        try:
            # Create a safety backup of current db before restoring
            if self.db_path.exists():
                safety_backup = (
                    self.backup_dir / f"pre_restore_{datetime.now().isoformat()}.sqlite"
                )
                shutil.copy2(self.db_path, safety_backup)
                log.info(f"Safety backup created: {safety_backup}")

            # Decompress and restore
            with gzip.open(backup_file, "rb") as f_in:
                with open(self.db_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)

            log.info(f"Database restored from: {backup_file}")
            return True

        except Exception as e:
            log.error(f"Restore failed: {e}")
            return False

    def _rotate_backups(self) -> None:
        """Remove old backups beyond the keep limit."""
        try:
            # Get all backup files sorted by modification time
            backups = sorted(
                self.backup_dir.glob("loft_db_*.sqlite.gz"),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )

            # Delete old backups
            for backup in backups[self.backup_count :]:
                backup.unlink()
                log.info(f"Deleted old backup: {backup}")

        except Exception as e:
            log.warning(f"Backup rotation failed: {e}")

    def cleanup_old_backups(self, days: int = 30) -> int:
        """Delete backups older than specified days.
        
        Args:
            days: Delete backups older than this many days
            
        Returns:
            Number of backups deleted
        """
        cutoff = datetime.now() - timedelta(days=days)
        cutoff_timestamp = cutoff.timestamp()
        deleted_count = 0

        try:
            for backup in self.backup_dir.glob("loft_db_*.sqlite.gz"):
                if backup.stat().st_mtime < cutoff_timestamp:
                    backup.unlink()
                    deleted_count += 1
                    log.info(f"Deleted old backup: {backup}")

        except Exception as e:
            log.error(f"Cleanup failed: {e}")

        return deleted_count

    def list_backups(self) -> list[dict]:
        """List all available backups.
        
        Returns:
            List of backup info dicts with name, size, and timestamp
        """
        backups = []
        try:
            for backup in sorted(
                self.backup_dir.glob("loft_db_*.sqlite.gz"),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            ):
                stat = backup.stat()
                backups.append(
                    {
                        "filename": backup.name,
                        "size": stat.st_size,
                        "created": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    }
                )
        except Exception as e:
            log.error(f"Failed to list backups: {e}")

        return backups

    def get_status(self) -> dict:
        """Get backup status information.
        
        Returns:
            Dictionary with backup stats
        """
        backups = self.list_backups()
        total_size = sum(b["size"] for b in backups)

        return {
            "total_backups": len(backups),
            "backups": backups,
            "total_size": total_size,
            "last_backup": backups[0]["created"] if backups else None,
        }
