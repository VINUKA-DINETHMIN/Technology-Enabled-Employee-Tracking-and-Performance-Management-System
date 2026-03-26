"""
R26-IT-042 — Employee Activity Monitoring System
config/__init__.py

Exposes the Settings singleton and break configuration.
"""

from config.settings import settings
from config.break_config import BreakConfig

__all__ = ["settings", "BreakConfig"]
