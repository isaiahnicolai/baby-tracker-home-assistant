"""
sqlite3 with this package's connection settings.

The client opens a short-lived connection for each query, from the Home
Assistant executor, and a refresh can overlap a service call. So every
connection waits (up to BUSY_TIMEOUT_SECONDS) for a lock instead of failing at
once with "database is locked", and the database uses write-ahead logging so
readers don't block the writer.

Modules import this as ``sqlite3`` (``from . import dbconn as sqlite3``): it
re-exports everything in the standard module (Row, the error classes, ...) and
replaces only ``connect``.
"""
import logging
import os
import sqlite3 as _sqlite3
from sqlite3 import *  # noqa: F401,F403 - Row, IntegrityError, ... are used as sqlite3.<name>

_LOGGER = logging.getLogger(__name__)

BUSY_TIMEOUT_SECONDS = 10


def remove_sidecar_files(database):
    """
    Delete the -wal and -shm files WAL mode keeps beside a database. Call it when
    the database file is deleted or replaced: a stale -wal left by a crash would
    otherwise be replayed onto the new file.
    """
    for suffix in ("-wal", "-shm"):
        try:
            os.remove(f"{database}{suffix}")
        except FileNotFoundError:
            pass
        except OSError as err:
            _LOGGER.warning("Could not delete %s%s: %s", database, suffix, err)


def connect(database, *args, **kwargs):
    """Open a connection that waits for locks and uses write-ahead logging."""
    kwargs.setdefault("timeout", BUSY_TIMEOUT_SECONDS)
    conn = _sqlite3.connect(database, *args, **kwargs)
    try:
        # Persistent once set; a cheap no-op on later connections
        conn.execute("PRAGMA journal_mode=WAL")
        # In WAL mode NORMAL still survives an application crash; it only skips
        # the fsync per commit that makes replaying history crawl on slow disks
        # and Docker bind mounts. (Per connection, so set it every time.)
        conn.execute("PRAGMA synchronous=NORMAL")
    except _sqlite3.OperationalError as err:
        _LOGGER.debug("Could not switch %s to WAL mode: %s", database, err)
    return conn
