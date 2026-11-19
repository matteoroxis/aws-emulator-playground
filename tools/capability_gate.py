"""Capability gate: checks that the AWS Emulator in use supports every operation this project relies on.

Each check has an expectation:
  supported  - must work; a NotImplemented answer or any error fails the gate.
  known-gap  - known to be missing in the emulator, or to behave differently from AWS; those outcomes
               are accepted. If it starts to work like AWS, the gate passes and emits a notice so the
               expectation (and any workaround in the code) can be removed.

Writes a Markdown table to $GITHUB_STEP_SUMMARY (when set) and JSON to .emulator/capabilities.json.
Usage: python -m tools.capability_gate [--strict-gaps]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import zipfile
from dataclasses import asdict, dataclass
from enum import StrEnum
from io import BytesIO

from botocore.exceptions import ClientError

from tools.aws_helpers import (
    OUTPUT_DIR,
    PLACEHOLDER_ROLE_ARN,
    ca_bundle,
    error_code,
    http_status,
    unique_suffix,
    wait_until,
)


class Outcome(StrEnum):
    OK = "ok"
    NOT_IMPLEMENTED = "not-implemented"
    DIFFERS = "differs-from-aws"
    ERROR = "error"


class Expect(StrEnum):
    SUPPORTED = "supported"
    KNOWN_GAP = "known-gap"


class NotImplementedByEmulator(Exception):
    """Raised by HTTP checks when the emulator answers 501."""


class DiffersFromAws(Exception):
    """Raised when the emulator answers, but not the way AWS documents it."""


@dataclass
class Result:
    service: str
    check: str
    expect: Expect
    outcome: Outcome
    detail: str
    verdict: str = ""


def classify(exc: BaseException) -> Outcome:
    if isinstance(exc, DiffersFromAws):
        return Outcome.DIFFERS
    if isinstance(exc, NotImplementedByEmulator):
        return Outcome.NOT_IMPLEMENTED
    if isinstance(exc, ClientError) and (error_code(exc) == "NotImplemented" or http_status(exc) == 501):
        return Outcome.NOT_IMPLEMENTED
    return Outcome.ERROR


def judge(expect: Expect, outcome: Outcome) -> str:
    """Returns pass | fail | gap-closed."""
    if outcome is Outcome.ERROR:
        return "fail"
    if expect is Expect.SUPPORTED:
        return "pass" if outcome is Outcome.OK else "fail"
    return "gap-closed" if outcome is Outcome.OK else "pass"


def _tiny_zip(name: str, content: str) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, content)
    return buf.getvalue()


def build_checks(clients, ctx: dict):
    """Ordered (service, check, expect, fn) tuples. fn returns a short detail string or raises."""
    import httpx

    ddb, s3, lam, lw = clients["dynamodb"], clients["s3"], clients["lambda"], clients["lambda-web"]
    sfx = unique_suffix()
    ctx.update(table=f"gate-items-{sfx}", bucket=f"gate-code-{sfx}", fn=f"gate-event-{sfx}", web=f"gate-web-{sfx}")

    def create_table():
        ddb.create_table(
            TableName=ctx["table"],
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        )
        ddb.get_waiter("table_exists").wait(TableName=ctx["table"], WaiterConfig={"Delay": 1})
        return "ACTIVE"

    def put_conditional():
        args = dict(TableName=ctx["table"], Item={"id": {"S": "a"}}, ConditionExpression="attribute_not_exists(id)")
        ddb.put_item(**args)
        try:
            ddb.put_item(**args)
        except ddb.exceptions.ConditionalCheckFailedException:
            return "second put rejected with ConditionalCheckFailedException"
        raise AssertionError("duplicate put was accepted")

    def get_item():
        item = ddb.get_item(TableName=ctx["table"], Key={"id": {"S": "a"}}).get("Item")
        assert item == {"id": {"S": "a"}}, item
        return "item read back"

    def scan():
        return f"Count={ddb.scan(TableName=ctx['table'], Limit=100)['Count']}"

    def delete_conditional():
        args = dict(TableName=ctx["table"], Key={"id": {"S": "a"}}, ConditionExpression="attribute_exists(id)")
        ddb.delete_item(**args)
        try:
            ddb.delete_item(**args)
        except ddb.exceptions.ConditionalCheckFailedException:
            return "second delete rejected with ConditionalCheckFailedException"
        raise AssertionError("delete of a missing item was accepted")

    def s3_upload():
        s3.create_bucket(Bucket=ctx["bucket"])
        s3.put_object(Bucket=ctx["bucket"], Key="web.zip", Body=_tiny_zip("index.js", "// noop\n"))
        return "bucket + object"

    def create_web_function():
        resp = lw.create_web_function(
            functionName=ctx["web"],
            revisionConfig={
                "buildConfig": {
                    "codeConfig": {"s3Object": {"bucket": ctx["bucket"], "key": "web.zip"}},
                    "runtimeConfig": {"runtime": "nodejs24.x"},
                },
                "serviceConfig": {"executionRoleArn": PLACEHOLDER_ROLE_ARN},
            },
            endpointConfig={"endpointName": "default", "endpointType": "HomeRegion", "authType": "ApplicationManaged"},
        )
        ctx["web_arn"] = resp["functionArn"]
        return f"state={resp['state']}"

    def web_function_active():
        fn = wait_until(lambda: lw.get_web_function(functionName=ctx["web"]), lambda r: r["state"] != "Pending")
        assert fn["state"] == "Active", fn
        return "Active"

    def web_revisions():
        revs = lw.list_web_function_revisions(functionName=ctx["web"])["revisions"]
        return f"{len(revs)} revision(s), states={[r['state'] for r in revs]}"

    def web_endpoint():
        ep = wait_until(
            lambda: lw.get_web_function_endpoint(functionName=ctx["web"], endpointName="default"),
            lambda r: r["state"] != "Pending",
        )
        assert ep["state"] == "Active", ep
        ctx["web_domain"] = ep["domainName"]
        return f"Active, domainName={ep['domainName']}"

    def list_web_endpoints():
        return f"{len(lw.list_web_function_endpoints(functionName=ctx['web'])['endpoints'])} endpoint(s)"

    def web_traffic():
        r = httpx.get(f"https://{ctx['web_domain']}/", verify=ca_bundle(), timeout=15)
        if r.status_code == 501:
            raise NotImplementedByEmulator(r.text.strip()[:160])
        return f"HTTP {r.status_code}"

    def create_event_function():
        # Returns rawPath when called through a Function URL, "pong" on a plain Invoke.
        code = "def handler(event, context):\n    return {'statusCode': 200, 'body': event.get('rawPath') or 'pong'}\n"
        lam.create_function(
            FunctionName=ctx["fn"],
            Runtime="python3.13",
            Handler="app.handler",
            Role=PLACEHOLDER_ROLE_ARN,
            Code={"ZipFile": _tiny_zip("app.py", code)},
        )
        wait_until(
            lambda: lam.get_function(FunctionName=ctx["fn"])["Configuration"],
            lambda c: c.get("State") != "Pending",
        )
        return "python3.13 Active"

    def invoke():
        out = lam.invoke(FunctionName=ctx["fn"], Payload=b"{}")
        payload = json.loads(out["Payload"].read())
        assert out.get("FunctionError") is None and payload.get("body") == "pong", payload
        return "code executed"

    def function_url_denied_without_policy():
        ctx["url"] = lam.create_function_url_config(FunctionName=ctx["fn"], AuthType="NONE")["FunctionUrl"]
        r = httpx.get(ctx["url"], verify=ca_bundle(), timeout=30)
        assert r.status_code == 403, f"expected 403 without resource policy, got {r.status_code}"
        return "403 as on AWS"

    def function_url_allowed_with_policy():
        lam.add_permission(
            FunctionName=ctx["fn"],
            StatementId="public-url",
            Action="lambda:InvokeFunctionUrl",
            Principal="*",
            FunctionUrlAuthType="NONE",
        )
        r = httpx.get(ctx["url"], verify=ca_bundle(), timeout=30)
        assert r.status_code == 200, (r.status_code, r.text[:200])
        return "200"

    def function_url_raw_path():
        r = httpx.get(ctx["url"].rstrip("/") + "/probe/path", verify=ca_bundle(), timeout=30)
        assert r.status_code == 200, (r.status_code, r.text[:200])
        if r.text != "/probe/path":
            raise DiffersFromAws(f"rawPath={r.text!r}, AWS sends '/probe/path'")
        return "rawPath='/probe/path'"

    S, G = Expect.SUPPORTED, Expect.KNOWN_GAP
    return [
        ("dynamodb", "CreateTable (on-demand)", S, create_table),
        ("dynamodb", "PutItem with attribute_not_exists", S, put_conditional),
        ("dynamodb", "GetItem", S, get_item),
        ("dynamodb", "Scan", S, scan),
        ("dynamodb", "DeleteItem with attribute_exists", S, delete_conditional),
        ("s3", "CreateBucket + PutObject", S, s3_upload),
        ("lambda-web", "CreateWebFunction", S, create_web_function),
        ("lambda-web", "GetWebFunction -> Active", S, web_function_active),
        ("lambda-web", "ListWebFunctionRevisions", S, web_revisions),
        ("lambda-web", "GetWebFunctionEndpoint -> Active", S, web_endpoint),
        ("lambda-web", "ListWebFunctionEndpoints", G, list_web_endpoints),
        ("lambda-web", "HTTP traffic on the endpoint (runs our code)", G, web_traffic),
        ("lambda", "CreateFunction python3.13", S, create_event_function),
        ("lambda", "Invoke", S, invoke),
        ("lambda", "Function URL denied without resource policy", S, function_url_denied_without_policy),
        ("lambda", "Function URL after AddPermission", S, function_url_allowed_with_policy),
        ("lambda", "Function URL rawPath without routing prefix", G, function_url_raw_path),
    ]


def cleanup(clients, ctx: dict) -> None:
    steps = [
        lambda: clients["lambda-web"].delete_web_function(functionName=ctx["web"]),
        lambda: clients["lambda"].delete_function(FunctionName=ctx["fn"]),
        lambda: clients["dynamodb"].delete_table(TableName=ctx["table"]),
    ]
    for step in steps:
        try:
            step()
        except Exception:  # noqa: BLE001 - best effort, emulator state is in memory anyway
            pass


def run(clients) -> list[Result]:
    ctx: dict = {}
    results: list[Result] = []
    failed_services: set[str] = set()
    try:
        for service, check, expect, fn in build_checks(clients, ctx):
            if service in failed_services and expect is Expect.SUPPORTED:
                results.append(Result(service, check, expect, Outcome.ERROR, "skipped: earlier step failed", "fail"))
                continue
            try:
                outcome, detail = Outcome.OK, fn()
            except Exception as exc:  # noqa: BLE001 - every failure becomes a reported outcome
                outcome, detail = classify(exc), f"{type(exc).__name__}: {exc}"[:240]
            verdict = judge(expect, outcome)
            if verdict == "fail":
                failed_services.add(service)
            results.append(Result(service, check, expect, outcome, detail, verdict))
    finally:
        cleanup(clients, ctx)
    return results


ICONS = {"pass": "✅", "fail": "❌", "gap-closed": "🎉"}


def to_markdown(results: list[Result], version: str) -> str:
    lines = [
        f"### AWS Emulator capability gate ({version})",
        "",
        "| | Service | Check | Expected | Outcome | Detail |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        detail = r.detail.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {ICONS[r.verdict]} | {r.service} | {r.check} | {r.expect} | {r.outcome} | {detail} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    import boto3

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--strict-gaps", action="store_true", help="fail when a known gap starts working")
    args = parser.parse_args(argv)

    clients = {name: boto3.client(name) for name in ("dynamodb", "s3", "lambda", "lambda-web")}
    results = run(clients)
    version = os.environ.get("EMULATOR_VERSION_INSTALLED", os.environ.get("EMULATOR_VERSION", "unknown"))

    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / "capabilities.json").write_text(json.dumps([asdict(r) for r in results], indent=2))
    report = to_markdown(results, version)
    print(report)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(report)

    for r in results:
        if r.verdict == "gap-closed":
            print(f"::notice title=Emulator gap closed::{r.service} / {r.check} now works - update the expectation")
        elif r.verdict == "fail":
            print(f"::error title=Emulator capability missing::{r.service} / {r.check}: {r.detail}")

    failed = [r for r in results if r.verdict == "fail" or (args.strict_gaps and r.verdict == "gap-closed")]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
