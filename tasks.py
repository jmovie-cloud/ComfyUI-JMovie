"""Persist submission reservations before initiating a billable request."""

import asyncio
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3

import folder_paths
from comfy.model_management import throw_exception_if_processing_interrupted

from .transport import RequestError


TASK_ID = re.compile(r"[A-Za-z0-9_-]{1,160}")
TERMINAL = {"failed", "cancelled", "canceled", "expired"}
PENDING = {"queued", "pending", "running", "processing"}
POLL_SECONDS = 10
WAIT_SECONDS = 15 * 60


def task_id(value):
    if not isinstance(value, str) or not TASK_ID.fullmatch(value):
        raise ValueError("Invalid cloud task ID.")
    return value


def fingerprint(*values):
    encoded = json.dumps(values, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class TaskStore:
    def __init__(self):
        directory = Path(folder_paths.get_user_directory()) / "jmovie-cloud"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = directory / "tasks.sqlite3"
        self.path.touch(mode=0o600, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    request_key TEXT PRIMARY KEY,
                    remote_id TEXT
                )
            """)

    def reserve(self, key):
        with closing(sqlite3.connect(self.path)) as db, db:
            cursor = db.execute("INSERT OR IGNORE INTO tasks VALUES (?, NULL)", (key,))
            if cursor.rowcount == 1:
                return True, None
            remote = db.execute("SELECT remote_id FROM tasks WHERE request_key = ?", (key,)).fetchone()
            return False, remote[0]

    def remember(self, key, remote_id):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE tasks SET remote_id = ? WHERE request_key = ?", (remote_id, key))

    def release(self, key):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM tasks WHERE request_key = ? AND remote_id IS NULL", (key,))


async def run_task(*, scope, payload, run_number, resume_id, submit, query, download, idempotent=False):
    if resume_id:
        remote_id = task_id(resume_id)
    else:
        store = TaskStore()
        key = fingerprint(scope, payload, run_number)
        is_new, remote_id = store.reserve(key)
        if is_new or (remote_id is None and idempotent):
            try:
                remote_id = task_id(await submit(key))
            except RequestError as error:
                if error.status in {400, 401, 402, 403, 404, 413, 415, 422, 429}:
                    store.release(key)
                    raise
                if idempotent:
                    raise RuntimeError("Submission unconfirmed. Queue the same JMovie run to recover its task ID.") from None
                raise RuntimeError("Submission unconfirmed. Check cloud task history before starting a new run.") from None
            except ValueError:
                if idempotent:
                    raise RuntimeError("JMovie returned no task ID. Queue the same run to recover it.") from None
                raise RuntimeError("Submission returned no usable task ID. Check cloud task history.") from None
            store.remember(key, remote_id)
        elif remote_id is None:
            raise RuntimeError(
                "This run has a pending or unconfirmed submission. Check cloud task history and "
                "use the recovered task ID to resume the run."
            )

    last_status = None
    try:
        async with asyncio.timeout(WAIT_SECONDS):
            while True:
                throw_exception_if_processing_interrupted()
                try:
                    status, result = await query(remote_id)
                except RequestError as error:
                    if error.status not in {None, 408, 429, 500, 502, 503, 504}:
                        raise RuntimeError(f"Task {remote_id} query returned HTTP {error.status}.") from None
                else:
                    if not isinstance(status, str):
                        raise RuntimeError(f"Task {remote_id} returned an invalid status.")
                    if status == "succeeded":
                        try:
                            return await download(result), remote_id
                        except RuntimeError:
                            raise RuntimeError(f"Task {remote_id} succeeded but its result could not be downloaded.") from None
                    if status in TERMINAL:
                        raise RuntimeError(f"Task {remote_id} ended with status {status}.")
                    if status not in PENDING:
                        raise RuntimeError(f"Task {remote_id} returned an unknown status.")
                    last_status = status
                await asyncio.sleep(POLL_SECONDS)
    except TimeoutError:
        raise RuntimeError(
            f"Task {remote_id} is still active ({last_status or 'status unavailable'}). "
            "Queue the same run to resume polling."
        ) from None
