"""File tailing receiver — watches log files via watchfiles (Rust inotify).

Supports glob patterns, log rotation detection (inode change + truncation),
offset checkpoint persistence (JSON with atomic write), and restart recovery.

NOT thread-safe — create one instance per event loop.
"""

from __future__ import annotations
