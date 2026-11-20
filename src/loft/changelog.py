"""Changelog and release notes management for Loft.

Serves changelog entries and What's New information to the UI.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


class ChangelogEntry:
    """A single changelog entry for a version."""

    def __init__(self, version: str, date: str, sections: dict[str, list[str]]):
        """Initialize a changelog entry.
        
        Args:
            version: Version string (e.g., "0.1.1")
            date: Date string (e.g., "2026-11-20")
            sections: Dict of section_name -> list of bullet points
        """
        self.version = version
        self.date = date
        self.sections = sections

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "version": self.version,
            "date": self.date,
            "sections": self.sections,
        }


class ChangelogParser:
    """Parses CHANGELOG.md files."""

    @staticmethod
    def parse_file(changelog_path: Path) -> list[ChangelogEntry]:
        """Parse a CHANGELOG.md file.
        
        Args:
            changelog_path: Path to CHANGELOG.md
            
        Returns:
            List of ChangelogEntry objects
        """
        if not changelog_path.exists():
            return []

        with open(changelog_path, "r") as f:
            content = f.read()

        entries = []
        
        # Find all version sections: ## [0.1.1] - 2026-11-20
        version_pattern = r"## \[([^\]]+)\] - ([^\n]+)"
        
        for match in re.finditer(version_pattern, content):
            version = match.group(1)
            date = match.group(2)
            
            # Find the content between this version and the next
            start = match.end()
            next_match = re.search(version_pattern, content[start:])
            end = start + next_match.start() if next_match else len(content)
            
            version_content = content[start:end]
            
            # Parse sections
            sections = {}
            section_pattern = r"### ([^\n]+)\n((?:- [^\n]*\n?)*)"
            
            for section_match in re.finditer(section_pattern, version_content):
                section_name = section_match.group(1)
                section_bullets = section_match.group(2)
                
                # Parse bullet points
                bullets = [
                    line.strip("- ").strip()
                    for line in section_bullets.split("\n")
                    if line.strip().startswith("-")
                ]
                
                if bullets:
                    sections[section_name] = bullets
            
            if sections:
                entries.append(ChangelogEntry(version, date, sections))
        
        return entries

    @staticmethod
    def get_latest_entry(changelog_path: Path) -> Optional[ChangelogEntry]:
        """Get the most recent changelog entry.
        
        Args:
            changelog_path: Path to CHANGELOG.md
            
        Returns:
            Latest ChangelogEntry or None
        """
        entries = ChangelogParser.parse_file(changelog_path)
        return entries[0] if entries else None

    @staticmethod
    def get_entry_for_version(
        changelog_path: Path, version: str
    ) -> Optional[ChangelogEntry]:
        """Get changelog entry for a specific version.
        
        Args:
            changelog_path: Path to CHANGELOG.md
            version: Version string to look for
            
        Returns:
            ChangelogEntry or None if not found
        """
        entries = ChangelogParser.parse_file(changelog_path)
        for entry in entries:
            if entry.version == version:
                return entry
        return None


def get_changelog_manager(cfg) -> ChangelogManager:
    """Get the global changelog manager instance."""
    return ChangelogManager(cfg.root / "CHANGELOG.md")


class ChangelogManager:
    """Manages changelog access and What's New notifications."""

    def __init__(self, changelog_path: Path):
        """Initialize changelog manager.
        
        Args:
            changelog_path: Path to CHANGELOG.md file
        """
        self.changelog_path = changelog_path

    def get_latest(self) -> Optional[dict]:
        """Get the latest changelog entry as dict.
        
        Returns:
            Latest changelog entry or None
        """
        entry = ChangelogParser.get_latest_entry(self.changelog_path)
        return entry.to_dict() if entry else None

    def get_all(self) -> list[dict]:
        """Get all changelog entries.
        
        Returns:
            List of changelog entries as dicts
        """
        entries = ChangelogParser.parse_file(self.changelog_path)
        return [entry.to_dict() for entry in entries]

    def get_for_version(self, version: str) -> Optional[dict]:
        """Get changelog for a specific version.
        
        Args:
            version: Version string
            
        Returns:
            Changelog entry or None
        """
        entry = ChangelogParser.get_entry_for_version(self.changelog_path, version)
        return entry.to_dict() if entry else None
