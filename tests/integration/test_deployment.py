"""Integration tests: checks what tools/deploy.py created on the emulator."""

import json
import os

import boto3
import httpx
import pytest

from tools.aws_helpers import OUTPUT_DIR, ca_bundle

pytestmark = pytest.mark.emulator


@pytest.fixture(scope="module")
def outputs():
    path = OUTPUT_DIR / "outputs.json"
    if not path.exists():
        pytest.skip("run `python -m tools.deploy` first")
    return json.loads(path.read_text())


def test_table_schema(outputs):
    table = boto3.client("dynamodb").describe_table(TableName=outputs["table"])["Table"]
    assert table["TableStatus"] == "ACTIVE"
    assert table["KeySchema"] == [{"AttributeName": "id", "KeyType": "HASH"}]
    assert table["BillingModeSummary"]["BillingMode"] == "PAY_PER_REQUEST"


def test_web_function_revision_and_endpoint_active(outputs):
    lw = boto3.client("lambda-web")
    name = outputs["web_function"]["name"]
    assert lw.get_web_function(functionName=name)["state"] == "Active"
    revisions = lw.list_web_function_revisions(functionName=name)["revisions"]
    assert [r["state"] for r in revisions] == ["Active"]
    endpoint = lw.get_web_function_endpoint(functionName=name, endpointName="default")
    assert endpoint["state"] == "Active"
    assert endpoint["authType"] == "ApplicationManaged"
    assert sum(w["weight"] for w in endpoint["revisionWeights"]) == 100


def test_web_function_environment_has_table(outputs):
    lw = boto3.client("lambda-web")
    name = outputs["web_function"]["name"]
    rev_id = lw.list_web_function_revisions(functionName=name)["revisions"][0]["revisionId"]
    rev = lw.get_web_function_revision(functionName=name, revisionId=rev_id)
    env = rev.get("revisionConfig", rev).get("serviceConfig", {}).get("environmentVariables", {})
    if not env:
        pytest.skip(f"revision detail does not expose environment variables: keys={sorted(rev)}")
    assert env["TABLE_NAME"] == outputs["table"]


@pytest.mark.xfail(strict=True, reason="AWS Emulator does not run Web Function code yet (endpoint answers 501)")
def test_web_function_endpoint_serves_our_code(outputs):
    domain = outputs["web_function"]["endpoint_domain"]
    r = httpx.get(f"https://{domain}/health", verify=ca_bundle(), timeout=15)
    assert r.status_code == 200 and r.json()["impl"] == "web-function"


def test_function_url_policy_is_public(outputs):
    policy = json.loads(boto3.client("lambda").get_policy(FunctionName=outputs["event_function"]["name"])["Policy"])
    actions = {s["Action"] for s in policy["Statement"]}
    assert "lambda:InvokeFunctionUrl" in actions


def test_env_points_at_emulator():
    assert os.environ.get("AWS_ENDPOINT_URL", "").startswith("https://127.0.0.1:")
