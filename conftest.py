"""Pytest configuration shared by every test module.

:mod:`database` binds its engine to ``RELAY_DATABASE_URL`` at import time, so
the scratch default has to be chosen before any test module imports it.  pytest
loads this file before collecting tests, which makes it the one place that
decides where tests are allowed to write.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

DEV_DATABASE_FILENAME = "agent-relay.db"


def default_test_database_url() -> str:
    """A scratch SQLite file inside the platform temp directory.

    ``/tmp`` does not exist on Windows, so the directory comes from
    :func:`tempfile.gettempdir`.  ``as_posix`` keeps the URL well formed for a
    drive-letter path (``sqlite:///C:/Users/.../agent-relay-test.db``) as well
    as for a POSIX absolute path (``sqlite:////tmp/agent-relay-test.db``).
    """

    scratch = Path(tempfile.gettempdir()) / "agent-relay-test.db"
    return f"sqlite:///{scratch.as_posix()}"


# Respect an explicit URL (CI may point at PostgreSQL); otherwise isolate.
os.environ.setdefault("RELAY_DATABASE_URL", default_test_database_url())

from database import DATABASE_URL  # noqa: E402  (must follow the default above)

# The fixtures below drop and recreate every table, so refuse to start at all
# if that would destroy the development database.
if Path(DATABASE_URL.split("?", 1)[0]).name == DEV_DATABASE_FILENAME:
    raise RuntimeError(
        f"Tests drop and recreate every table; refusing to run against {DATABASE_URL!r}. "
        "Unset RELAY_DATABASE_URL to use the scratch default, or point it at a throwaway database."
    )
