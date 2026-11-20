"""Automatic update checking and application for Loft.

Periodically checks GitHub releases for newer versions and notifies users.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx

log = logging.getLogger(__name__)

GITHUB_REPO = "Spinjitsudoom/Loft"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


@dataclass
class UpdateStatus:
    """Current update status of the application."""
    current_version: str
    latest_version: Optional[str] = None
    update_available: bool = False
    last_checked: Optional[datetime] = None
    error: Optional[str] = None


class UpdateChecker:
    """Checks for and applies Loft updates."""

    def __init__(self, current_version: str = "0.1.0"):
        """Initialize the update checker.
        
        Args:
            current_version: The current version of Loft
        """
        self.current_version = current_version
        self.status = UpdateStatus(current_version=current_version)
        self._last_check: Optional[datetime] = None
        self._check_interval = timedelta(hours=24)  # Check once per day

    def should_check(self) -> bool:
        """Whether enough time has passed to check for updates again."""
        if self._last_check is None:
            return True
        return datetime.now() - self._last_check > self._check_interval

    async def check_for_updates(self) -> UpdateStatus:
        """Check GitHub for a newer release.
        
        Returns:
            UpdateStatus with latest version info and any errors
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    GITHUB_API,
                    timeout=5.0,
                    headers={"Accept": "application/vnd.github.v3+json"},
                )
                response.raise_for_status()
                data = response.json()

            latest_version = data.get("tag_name", "").lstrip("v")
            if not latest_version:
                self.status.error = "Could not parse version from GitHub"
                return self.status

            # Compare versions (simple semver comparison)
            if self._compare_versions(latest_version, self.current_version) > 0:
                self.status.latest_version = latest_version
                self.status.update_available = True
                log.info(
                    f"Update available: {self.current_version} → {latest_version}"
                )
            else:
                self.status.latest_version = latest_version
                self.status.update_available = False

            self.status.error = None
            self.status.last_checked = datetime.now()
            self._last_check = datetime.now()

        except httpx.TimeoutException:
            self.status.error = "Update check timed out"
            log.warning("Update check timed out")
        except httpx.HTTPError as e:
            self.status.error = f"Failed to check GitHub: {e}"
            log.warning(f"Failed to check GitHub: {e}")
        except Exception as e:
            self.status.error = f"Unexpected error: {e}"
            log.error(f"Update check error: {e}")

        return self.status

    @staticmethod
    def _compare_versions(v1: str, v2: str) -> int:
        """Compare two semantic versions.
        
        Returns:
            1 if v1 > v2
            -1 if v1 < v2
            0 if v1 == v2
        """
        try:
            parts1 = [int(x) for x in v1.split(".")[:3]]
            parts2 = [int(x) for x in v2.split(".")[:3]]

            # Pad with zeros
            while len(parts1) < 3:
                parts1.append(0)
            while len(parts2) < 3:
                parts2.append(0)

            if parts1 > parts2:
                return 1
            elif parts1 < parts2:
                return -1
            return 0
        except (ValueError, AttributeError):
            return 0

    async def apply_update_via_pip(self) -> bool:
        """Update Loft via pip (requires pip access).
        
        Returns:
            True if update succeeded, False otherwise
        """
        if not self.status.latest_version:
            log.warning("No update available")
            return False

        try:
            # Update via pip in a subprocess
            result = await self._run_command(
                ["pip", "install", "--upgrade", f"loft=={self.status.latest_version}"]
            )
            if result:
                log.info(f"Updated to {self.status.latest_version}")
                self.current_version = self.status.latest_version
                return True
        except Exception as e:
            log.error(f"Failed to apply update: {e}")

        return False

    @staticmethod
    async def _run_command(cmd: list[str]) -> bool:
        """Run a shell command asynchronously.
        
        Args:
            cmd: Command and arguments to run
            
        Returns:
            True if command succeeded (exit code 0)
        """
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            log.error(f"Command timed out: {' '.join(cmd)}")
            return False
        except Exception as e:
            log.error(f"Failed to run command: {e}")
            return False

    def get_status(self) -> dict:
        """Get the current update status as a dict.
        
        Returns:
            Dictionary with version and update info
        """
        return {
            "current_version": self.status.current_version,
            "latest_version": self.status.latest_version,
            "update_available": self.status.update_available,
            "last_checked": (
                self.status.last_checked.isoformat()
                if self.status.last_checked
                else None
            ),
            "error": self.status.error,
        }


# Global update checker instance
_checker: Optional[UpdateChecker] = None


def get_checker() -> UpdateChecker:
    """Get the global update checker instance."""
    global _checker
    if _checker is None:
        from importlib.metadata import version as get_version

        try:
            current_version = get_version("loft")
        except Exception:
            current_version = "0.1.0"

        _checker = UpdateChecker(current_version)

    return _checker
