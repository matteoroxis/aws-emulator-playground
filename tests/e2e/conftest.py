"""The e2e suite runs the same HTTP contract against every available target:

web-function   WEB_LOCAL_URL  - the Web Function's server run as a local process, data on the emulator
function-url   FUNCTION_URL   - the Event Function served by the emulator's Function URL
"""

import os
import uuid

import httpx
import pytest

from tools.aws_helpers import ca_bundle

TARGETS = {
    "web-function": ("WEB_LOCAL_URL", "web-function"),
    "function-url": ("FUNCTION_URL", "event-function"),
}


@pytest.fixture(params=list(TARGETS), scope="module")
def target(request):
    env_var, impl = TARGETS[request.param]
    base = os.environ.get(env_var)
    if not base:
        pytest.skip(f"{env_var} not set")
    with httpx.Client(base_url=base.rstrip("/"), verify=ca_bundle(), timeout=30) as client:
        yield client, impl


@pytest.fixture
def api(target):
    return target[0]


@pytest.fixture
def impl(target):
    return target[1]


@pytest.fixture
def new_id():
    return f"e2e-{uuid.uuid4().hex[:12]}"
