"""Deploys the Items API to the AWS Emulator (or any endpoint the AWS SDK is pointed at).

Creates:
  - DynamoDB table <prefix>-items
  - S3 bucket with the two code packages
  - Lambda Web Function (Node.js 24) with a default endpoint   -> functions/web
  - Event Function (python3.13) with a public Function URL     -> functions/event

Writes .emulator/outputs.json and, on GitHub Actions, exports TABLE_NAME, FUNCTION_URL,
WEB_FUNCTION_NAME and WEB_ENDPOINT_DOMAIN to $GITHUB_ENV.
Usage: python -m tools.deploy   (run `npm ci --omit=dev` in functions/web first)
"""

from __future__ import annotations

import json
import sys

import boto3

from tools.aws_helpers import (
    OUTPUT_DIR,
    PLACEHOLDER_ROLE_ARN,
    REPO_ROOT,
    append_github_env,
    unique_suffix,
    wait_until,
    zip_tree,
)

WEB_DIR = REPO_ROOT / "functions" / "web"
EVENT_DIR = REPO_ROOT / "functions" / "event"


def deploy() -> dict:
    sfx = unique_suffix()
    table, bucket = f"items-{sfx}", f"items-code-{sfx}"
    web_name, event_name = f"items-web-{sfx}", f"items-event-{sfx}"
    ddb, s3, lam, lw = (boto3.client(n) for n in ("dynamodb", "s3", "lambda", "lambda-web"))

    ddb.create_table(
        TableName=table,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
    )
    ddb.get_waiter("table_exists").wait(TableName=table, WaiterConfig={"Delay": 1})
    print(f"table {table}: ACTIVE")

    if not (WEB_DIR / "node_modules").is_dir():
        sys.exit("functions/web/node_modules missing: run `npm ci --omit=dev` in functions/web first")
    s3.create_bucket(Bucket=bucket)
    s3.put_object(Bucket=bucket, Key="web.zip", Body=zip_tree(WEB_DIR, ["package.json", "src", "node_modules"]))
    print(f"bucket {bucket}: web.zip uploaded")

    # --- Lambda Web Function --------------------------------------------------------------
    lw.create_web_function(
        functionName=web_name,
        revisionConfig={
            "description": f"items api {sfx}",
            "buildConfig": {
                "codeConfig": {"s3Object": {"bucket": bucket, "key": "web.zip"}},
                "runtimeConfig": {"runtime": "nodejs24.x"},
            },
            "serviceConfig": {
                "executionRoleArn": PLACEHOLDER_ROLE_ARN,
                "timeoutSeconds": 30,
                "environmentVariables": {"TABLE_NAME": table},
            },
        },
        endpointConfig={"endpointName": "default", "endpointType": "HomeRegion", "authType": "ApplicationManaged"},
    )
    fn = wait_until(lambda: lw.get_web_function(functionName=web_name), lambda r: r["state"] != "Pending")
    ep = wait_until(
        lambda: lw.get_web_function_endpoint(functionName=web_name, endpointName="default"),
        lambda r: r["state"] != "Pending",
    )
    if fn["state"] != "Active" or ep["state"] != "Active":
        sys.exit(f"web function not active: function={fn['state']} endpoint={ep['state']}")
    print(f"web function {web_name}: Active, endpoint {ep['domainName']}")

    # --- Event Function + Function URL ----------------------------------------------------
    lam.create_function(
        FunctionName=event_name,
        Runtime="python3.13",
        Handler="items_api.handler",
        Role=PLACEHOLDER_ROLE_ARN,
        Timeout=30,
        Code={"ZipFile": zip_tree(EVENT_DIR, ["items_api.py"])},
        Environment={"Variables": {"TABLE_NAME": table}},
    )
    wait_until(
        lambda: lam.get_function(FunctionName=event_name)["Configuration"], lambda c: c.get("State") != "Pending"
    )
    url = lam.create_function_url_config(FunctionName=event_name, AuthType="NONE")["FunctionUrl"]
    lam.add_permission(
        FunctionName=event_name,
        StatementId="public-function-url",
        Action="lambda:InvokeFunctionUrl",
        Principal="*",
        FunctionUrlAuthType="NONE",
    )
    print(f"event function {event_name}: Active, url {url}")

    return {
        "table": table,
        "bucket": bucket,
        "web_function": {"name": web_name, "arn": fn["functionArn"], "endpoint_domain": ep["domainName"]},
        "event_function": {"name": event_name, "url": url},
    }


def main() -> int:
    outputs = deploy()
    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / "outputs.json").write_text(json.dumps(outputs, indent=2))
    append_github_env(
        {
            "TABLE_NAME": outputs["table"],
            "FUNCTION_URL": outputs["event_function"]["url"],
            "WEB_FUNCTION_NAME": outputs["web_function"]["name"],
            "WEB_ENDPOINT_DOMAIN": outputs["web_function"]["endpoint_domain"],
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
