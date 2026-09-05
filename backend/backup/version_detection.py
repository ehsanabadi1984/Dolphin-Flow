"""
PostgreSQL version detection helpers for Backup/Restore compatibility.

These helpers are best-effort; they must never cause a backup or restore
to fail when version information is unavailable.
"""

import re
import subprocess
import logging

logger = logging.getLogger(__name__)


def detect_pg_dump_version(pg_dump_binary):
    """Detect the PostgreSQL pg_dump version string.

    Returns the version string (e.g. ``"16.3"``) or ``None`` when the
    version cannot be detected. Backup must not fail when version detection
    is unavailable, so this function always returns ``None`` on any error.
    """
    try:
        result = subprocess.run(
            [pg_dump_binary, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout:
            # Typical output: "pg_dump (PostgreSQL) 16.3"
            # Also tolerate: "pg_dump (PostgreSQL) 16.3 (Ubuntu ...)"
            match = re.search(
                r"pg_dump\s*\(PostgreSQL\)\s*([\d]+(?:\.[\d]+)*)",
                result.stdout,
            )
            if match:
                return match.group(1)
            # Fallback: look for the first version-like token.
            match = re.search(r"([\d]+(?:\.[\d]+)*)", result.stdout)
            if match:
                return match.group(1)
    except (OSError, subprocess.TimeoutExpired, Exception):
        logger.debug("Could not detect pg_dump version for %s", pg_dump_binary)

    return None


def extract_major_version(version_string):
    """Return the major version integer from a version string like ``"16.3"``.

    Returns ``None`` when the string is absent or unparseable.
    """
    if not version_string:
        return None

    try:
        major = int(version_string.split(".")[0])
        return major
    except (ValueError, IndexError):
        return None


def detect_pg_restore_version(pg_restore_binary):
    """Detect the PostgreSQL pg_restore version string.

    Returns the version string (e.g. ``"16.3"``) or ``None`` when the
    version cannot be detected. Restore must not fail when version detection
    is unavailable, but must fail when the detected version is incompatible.
    """
    try:
        result = subprocess.run(
            [pg_restore_binary, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout:
            # Typical output: "pg_restore (PostgreSQL) 16.3"
            match = re.search(
                r"pg_restore\s*\(PostgreSQL\)\s*([\d]+(?:\.[\d]+)*)",
                result.stdout,
            )
            if match:
                return match.group(1)
            # Fallback: look for the first version-like token.
            match = re.search(r"([\d]+(?:\.[\d]+)*)", result.stdout)
            if match:
                return match.group(1)
    except (OSError, subprocess.TimeoutExpired, Exception):
        logger.debug("Could not detect pg_restore version for %s", pg_restore_binary)

    return None


def pg_restore_supports_version_flag(pg_restore_binary):
    """Check whether ``pg_restore`` supports the ``--version`` flag.

    Older PostgreSQL releases may not support it; the check is best-effort
    and must never block a restore.
    """
    try:
        result = subprocess.run(
            [pg_restore_binary, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
