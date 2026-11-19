"""The e2e suite calls the Event Function through the Function URL that the emulator serves.

The emulator does not run Web Function code yet (its endpoint answers 501), so the Web Function is
covered by the integration tests (control plane) and by its own unit tests. See the xfail test in
tests/integration/test_deployment.py, which fails on purpose as soon as the endpoint starts to work.
"""

import os
import uuid

import httpx
import pytest

from tools.aws_helpers import ca_bundle


@pytest.fixture(scope="module")
def api():
    base = os.environ.get("FUNCTION_URL")
    if not base:
        pytest.skip("FUNCTION_URL not set (run tools/deploy.py first)")
    with httpx.Client(base_url=base.rstrip("/"), verify=ca_bundle(), timeout=30) as client:
        yield client


@pytest.fixture
def new_id():
    return f"e2e-{uuid.uuid4().hex[:12]}"
