# Spike: AWS Emulator with Lambda Web Functions, Function URLs and DynamoDB

Date: 19 November 2026. Host: an EC2 t3.large instance with Ubuntu 24.04 x86_64.
Versions: aws-emulator 1.0.522 (released 2026-11-19, commit 2a51eb7), AWS CLI 2.41.1, boto3/botocore 1.44.6, Node 24.22.3, Python 3.12.3.

These are the raw results of the experiments that came before the pipeline. The scripts used for the spike are not in this repository; `scripts/` and `tools/` replace them.

## Setup

- On Linux the emulator installs as a native `.deb` package, with no Docker. It starts with `aws-emulator -p 9297 --telemetry off`.
- It becomes healthy in less than a second: `/__admin/health` answered `200` after 314 to 559 ms in the runs we measured.
- Every start creates new credentials and a new CA in `~/.aws/emulator/<port>/`. `scripts/emulator/env.sh` points the AWS CLI and SDKs at them.

## Lambda Web Functions (`lambda-web`)

| Operation | Result |
|---|---|
| `ListWebFunctions`, `GetWebAccountSettings` | OK |
| `CreateWebFunction` (with `revisionConfig` and `endpointConfig`) | OK. State is `Pending`, then `Active` after about 0.5 s |
| `GetWebFunction`, `GetWebFunctionEndpoint`, `GetWebFunctionRevision`, `ListWebFunctionRevisions`, `ListTags` | OK |
| `ListWebFunctionEndpoints` | `NotImplemented`: "operation ListWebFunctionEndpoints is scaffolded but not implemented in this emulator" |
| HTTP traffic to the endpoint (`domainName` is `127.0.0.1:<port>`) | `501`: "This web function endpoint is not implemented: the emulator runs no web function code, so the handler's own response cannot be served." |

In short, the emulator supports the control plane of Web Functions but not the data plane: it never runs the function's code.

## Event Function in Python, DynamoDB and Function URL

- `CreateFunction` with `python3.13` works and the function becomes `Active`. `Invoke` really runs the code.
- Inside the function, `boto3.client("dynamodb")` reaches the emulator's DynamoDB, although no `AWS_ENDPOINT_URL*` variable is set in the function's environment. A `Scan` from outside the function sees the item that the function wrote.
- `CreateFunctionUrlConfig` with `AuthType` `NONE` returns a URL like `https://127.0.0.1:<port>/_aws/lambda-url/<id>/`.
  - With no resource-based policy, a call returns `403`, as on AWS. The emulator log says: "no resource-based policy allows the lambda:InvokeFunctionUrl action".
  - After `add-permission` (`lambda:InvokeFunctionUrl`, principal `*`, `FunctionUrlAuthType` `NONE`), a call returns `200` with an event in payload format 2.0.
- The event differs from AWS in one field: `rawPath` (and `requestContext.http.path`) contains the emulator's routing prefix. A `POST` to `<url>/items/abc?x=1` produced `rawPath: '/_aws/lambda-url/f6452ec6158b493bab282aa3b18a5d4f/items/abc'`. On AWS it would be `/items/abc`. `version`, `routeKey`, `rawQueryString`, `body` and `isBase64Encoded` looked as expected.

## Security

- Python code that the emulator runs has no network access to the host. Even `socket.gethostname()` fails with "a Lambda function in this emulator has no host network to reach". The code therefore cannot reach the instance metadata service of the host (and its real IAM role) or the internet.
- Calls from the function code to AWS services go to the emulator.
- An InfoWorld article says that the emulator does not sandbox executed code. Our test shows a sandbox for the Python Lambda runtime in version 1.0.522. Check this again with each new release.

## What this means for the project

- A Web Function cannot be tested end to end through the emulator's endpoint.
- The emulator can still check the deployment of a Web Function through the control plane: function, revision, endpoint and environment.
- The path through an Event Function and a Function URL can be tested end to end on the emulator. The only adjustment is removing the routing prefix from `rawPath`.
