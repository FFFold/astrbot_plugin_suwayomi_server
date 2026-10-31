"""Shared helpers for unit tests."""
from __future__ import annotations

import contextlib
import os


@contextlib.contextmanager
def umask(mask: int):
    """Run a block with a fixed process umask, restoring it afterwards."""
    old = os.umask(mask)
    try:
        yield
    finally:
        os.umask(old)
