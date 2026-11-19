"""Small helpers shared by the capability gate and the deploy script."""

from __future__ import annotations

import io
import os
import pathlib
import ssl
import time
import zipfile
from collections.abc import Callable, Iterable

from botocore.exceptions import ClientError

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / ".emulator"
# The emulator accepts any role ARN; on real AWS this would be a real execution role.
PLACEHOLDER_ROLE_ARN = "arn:aws:iam::000000000000:role/items-api-execution"


def unique_suffix() -> str:
    run = os.environ.get("GITHUB_RUN_ID")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    return f"{run}-{attempt}" if run else os.urandom(3).hex()


def zip_tree(root: pathlib.Path, include: Iterable[str]) -> bytes:
    """Zips the given files/directories (relative to root), skipping tests and caches."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in include:
            path = root / entry
            files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
            for f in files:
                if "__pycache__" in f.parts:
                    continue
                zf.write(f, f.relative_to(root).as_posix())
    return buf.getvalue()


def wait_until(fetch: Callable[[], object], done: Callable[[object], bool], timeout: float = 60, interval: float = 0.5):
    deadline = time.monotonic() + timeout
    while True:
        value = fetch()
        if done(value):
            return value
        if time.monotonic() > deadline:
            raise TimeoutError(f"condition not met within {timeout}s, last value: {value!r}")
        time.sleep(interval)


def error_code(exc: ClientError) -> str:
    return exc.response.get("Error", {}).get("Code", "")


def http_status(exc: ClientError) -> int | None:
    return exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")


def ca_bundle():
    """Verification setting for httpx: the emulator's CA if configured, else system trust."""
    cafile = os.environ.get("AWS_CA_BUNDLE")
    return ssl.create_default_context(cafile=cafile) if cafile else True


def append_github_env(values: dict[str, str]) -> None:
    target = os.environ.get("GITHUB_ENV")
    if not target:
        return
    with open(target, "a", encoding="utf-8") as fh:
        for key, value in values.items():
            fh.write(f"{key}={value}\n")
