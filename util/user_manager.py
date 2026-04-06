"""
utils/user_manager.py
=====================
Thread-safe AND cross-process user pool for pytest-xdist parallel runs.

ROOT CAUSE OF THE ORIGINAL BUG
--------------------------------
threading.Lock  only protects code within ONE process.
pytest-xdist spawns a separate OS process per worker (gw0, gw1 …).
So two workers could simultaneously:
  1.  gw0  opens users.json for writing (OS truncates file to 0 bytes)
  2.  gw4  reads the file mid-write  →  empty string  →  JSONDecodeError

TWO-LAYER FIX
-------------
1. filelock.FileLock  — OS-level advisory lock on users.json.lock
   Blocks ALL other processes until the current one releases it.
2. Atomic write via tempfile + os.replace()
   The JSON file is NEVER partially written.
   os.replace() is atomic on POSIX and near-atomic on Windows (NTFS).
3. Read-with-retry inside the lock — handles the tiny Windows window
   where replace() briefly leaves the file inaccessible.

HOW TO USE
----------
    from utils.user_manager import acquire_user, release_user, reset_all_users

    # In a pytest fixture:
    user = acquire_user("standard", worker_id="gw0")
    yield user
    release_user(user)
"""

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

# ------------------------------------------------------------------
# RESOLVE POOL PATH  (absolute, relative to THIS file's package root)
# Workers may have different CWDs — always use an absolute path.
# ------------------------------------------------------------------
_HERE      = Path(__file__).resolve().parent.parent   # AutomationFramework/
_POOL_PATH = _HERE / "users" / "users.json"
_LOCK_PATH = _HERE / "users" / "users.json.lock"      # advisory lock file

_POLL_INTERVAL   = 0.3    # seconds between retry checks
_USER_LOCK_TIMEOUT = 30   # seconds to wait for a free user
_FILE_LOCK_TIMEOUT = 10   # seconds to wait for the file lock itself

# In-process lock — prevents two threads in the SAME worker from colliding
_thread_lock = threading.Lock()

# ------------------------------------------------------------------
# FILELOCK — import with a clear error if not installed
# ------------------------------------------------------------------
try:
    from filelock import FileLock, Timeout as FileLockTimeout
    _FL = FileLock(str(_LOCK_PATH), timeout=_FILE_LOCK_TIMEOUT)
except ImportError:
    raise ImportError(
        "\n\n[UserPool] 'filelock' is required for parallel test safety.\n"
        "Install it:  pip install filelock\n"
        "Or add it to requirements.txt and re-run pip install.\n"
    )


# ==================================================================
# PUBLIC API
# ==================================================================

def acquire_user(role: str, worker_id: str = "main") -> dict:
    """
    Claim a free user of the requested role from the pool.

    Blocks until a user is free or _USER_LOCK_TIMEOUT seconds elapse.

    Parameters
    ----------
    role      : "admin" | "standard" | "readonly" | "mobile"
    worker_id : xdist worker id string ("gw0", "gw1" …) for tracing

    Returns
    -------
    dict  — copy of the user entry (id, username, password, role, api_token …)

    Raises
    ------
    TimeoutError  — no free user within timeout
    """
    deadline = time.time() + _USER_LOCK_TIMEOUT

    while time.time() < deadline:
        with _thread_lock:                          # in-process guard
            try:
                with _FL:                           # cross-process file lock
                    pool = _safe_read()
                    for user in pool:
                        if user["role"] == role and not user["in_use"]:
                            user["in_use"]    = True
                            user["locked_by"] = worker_id
                            _atomic_write(pool)
                            log.info(
                                f"[UserPool] ✅ Acquired '{user['username']}'"
                                f"  role={role}  worker={worker_id}"
                            )
                            return dict(user)
            except FileLockTimeout:
                log.warning(
                    f"[UserPool] Could not acquire file lock within "
                    f"{_FILE_LOCK_TIMEOUT}s — retrying …"
                )

        log.debug(
            f"[UserPool] No free '{role}' user right now — "
            f"retry in {_POLL_INTERVAL}s …"
        )
        time.sleep(_POLL_INTERVAL)

    raise TimeoutError(
        f"\n[UserPool] No free user with role='{role}' became available "
        f"within {_USER_LOCK_TIMEOUT}s.\n"
        f"  → Add more '{role}' accounts to {_POOL_PATH}\n"
        f"  → Or reduce pytest -n workers so fewer users are needed simultaneously."
    )


def release_user(user: dict) -> None:
    """
    Return a user to the free pool after a test completes.

    Parameters
    ----------
    user : the dict returned by acquire_user()
    """
    with _thread_lock:
        try:
            with _FL:
                pool = _safe_read()
                for u in pool:
                    if u["id"] == user["id"]:
                        u["in_use"]    = False
                        u["locked_by"] = None
                        _atomic_write(pool)
                        log.info(
                            f"[UserPool] 🔓 Released '{user['username']}'"
                        )
                        return
                log.warning(
                    f"[UserPool] id='{user.get('id')}' not found during release"
                )
        except FileLockTimeout:
            log.error(
                "[UserPool] Could not acquire file lock to RELEASE user "
                f"'{user.get('username')}' — user may remain locked."
            )


def reset_all_users() -> None:
    """
    Force every user to in_use=False.
    Call once at session start to clear locks from crashed runs.
    """
    with _thread_lock:
        try:
            with _FL:
                pool = _safe_read()
                for u in pool:
                    u["in_use"]    = False
                    u["locked_by"] = None
                _atomic_write(pool)
            log.info("[UserPool] 🔄 All users reset to free state")
        except FileLockTimeout:
            log.error("[UserPool] Could not acquire lock during reset — skipping reset")


def get_pool_status() -> list:
    """
    Return a snapshot of the current pool state (useful for debugging).
    Each entry: id, username, role, in_use, locked_by
    """
    with _thread_lock:
        with _FL:
            pool = _safe_read()
    return [
        {
            "id":        u["id"],
            "username":  u["username"],
            "role":      u["role"],
            "in_use":    u["in_use"],
            "locked_by": u["locked_by"],
        }
        for u in pool
    ]


# ==================================================================
# PRIVATE HELPERS
# ==================================================================

def _safe_read() -> list:
    """
    Read and parse users.json.
    Retries up to 3 times with a short delay to handle the tiny Windows
    window where os.replace() briefly makes the file unreadable.
    Must be called while _FL (file lock) is already held.
    """
    for attempt in range(3):
        try:
            text = _POOL_PATH.read_text(encoding="utf-8").strip()
            if not text:
                raise ValueError("users.json is empty")
            return json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            if attempt < 2:
                log.warning(
                    f"[UserPool] Read attempt {attempt+1} failed ({exc}) — "
                    f"retrying in 0.1s …"
                )
                time.sleep(0.1)
            else:
                raise RuntimeError(
                    f"[UserPool] users.json could not be read after 3 attempts: {exc}\n"
                    f"  Path: {_POOL_PATH}\n"
                    "  This usually means the file is corrupted. "
                    "Restore it from users/users.json in your repo."
                ) from exc


def _atomic_write(pool: list) -> None:
    """
    Write pool to users.json atomically using a temp file + os.replace().

    os.replace() is atomic on POSIX (Linux/macOS).
    On Windows (NTFS) it is NOT fully atomic but is as close as Python
    can get without third-party libraries — the file lock above ensures
    only one process is writing at a time, making the window negligible.

    Must be called while _FL (file lock) is already held.
    """
    content = json.dumps(pool, indent=2, ensure_ascii=False)

    # Write to a sibling temp file first
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=_POOL_PATH.parent,
        prefix=".users_tmp_",
        suffix=".json"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())   # ensure bytes hit disk before rename

        # Atomic rename — replaces users.json in one OS operation
        os.replace(tmp_path, str(_POOL_PATH))

    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
