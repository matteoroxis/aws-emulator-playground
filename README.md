# Items API on Lambda Web Functions, tested in CI with AWS Emulator

This repository has a small CRUD API on `/items`, backed by DynamoDB. The API exists in two forms with the same HTTP contract:

- `functions/web/` is a Lambda Web Function in Node.js 24. It is a plain HTTP server that listens on the address in `AWS_LAMBDA_HTTP_ENDPOINT`.
- `functions/event/` is a classic Lambda (an Event Function) in Python 3.13, exposed through a Function URL.

Every pull request to `main` runs on GitHub Actions. The workflow runs lint and unit tests, then installs [AWS Emulator](https://docs.aws.amazon.com/emulator/latest/userguide/) directly on the runner, with no Docker and no AWS account. When all three jobs pass, GitHub merges the pull request automatically.

## The API

| Method | Path | Result |
|---|---|---|
| `GET` | `/health` | `200 {"status": "ok", "impl": "web-function"}` (or `"event-function"`) |
| `POST` | `/items` | `201` with the new item. Body: `{"name": "...", "id": "optional"}`. `400` for invalid input, `409` if the id already exists |
| `GET` | `/items` | `200 {"items": [...]}`, up to 100 items |
| `GET` | `/items/{id}` | `200` with the item, or `404` |
| `DELETE` | `/items/{id}` | `204`, or `404` |

Unknown paths return `404`, a wrong method on a known path returns `405`, and a body larger than 64 KiB returns `413`. Errors have the form `{"error": "..."}`.

An item looks like `{"id": "...", "name": "...", "createdAt": "2026-01-01T00:00:00.000Z"}`. A `name` must be 1 to 100 characters; an `id` must match `[A-Za-z0-9_-]{1,64}`. Both implementations use conditional writes in DynamoDB, so a duplicate id or a delete of a missing item fails inside DynamoDB, not in application code.

## What the pipeline does

`.github/workflows/ci.yml` runs on pull requests to `main`, on pushes to `main` and on manual dispatch.

```
lint      ruff check, ruff format --check, node --check, shellcheck
unit      pytest tests/unit (Python routing and gate rules)
          node --test (the Web Function server with an in-memory repository)
emulator  install aws-emulator 1.0.522 (.deb package) and start it
          capability gate: check each AWS operation the project uses
          deploy: DynamoDB table, Web Function, Event Function with a Function URL
          start the Web Function server as a local process on the runner
          pytest tests/integration tests/e2e
          upload logs, JUnit reports and JSON outputs as an artifact
```

The jobs run in this order, and each one starts only if the one before it passed. The ruleset in `.github/rulesets/main.json` makes `lint`, `unit` and `emulator` required checks, so a pull request can only be merged when all three are green.

The e2e suite in `tests/e2e/` runs the same tests against two targets:

- `web-function`: the Node server from `functions/web/`, started on the runner by `scripts/start_web_function_local.sh`, with its data in the emulator's DynamoDB;
- `function-url`: the Python function from `functions/event/`, called through the emulator's Function URL.

For each target, one test also reads the new item straight from DynamoDB, to make sure the write reached the table in the emulator.

`.github/workflows/nightly-emulator-latest.yml` runs the same emulator steps every night at 03:17 UTC, but with the latest emulator release instead of the pinned one. It is not a required check, so it never blocks a merge. It runs the gate with `--strict-gaps`, which makes it fail when a known gap starts to work. That is the signal to update the gate and remove any workaround for that gap.

## The capability gate

`tools/capability_gate.py` runs 17 checks against the emulator on throwaway resources. At the end it deletes the functions and the table it created; the rest disappears when the emulator stops. Each check expects one of two things:

- `supported`: the operation must work like on AWS. Any other result fails the job.
- `known-gap`: the emulator is known to miss this, or to behave differently from AWS. That result is accepted. If the operation starts to work, the gate prints a notice (and fails with `--strict-gaps`).

The gate writes a Markdown table to the job summary on GitHub and saves the results in `.emulator/capabilities.json`, which is part of the uploaded artifact.

These are the three known gaps, checked with aws-emulator 1.0.522 (released on 19 November 2026):

| Behaviour | What the emulator does | How the project handles it |
|---|---|---|
| HTTP traffic to the Web Function endpoint | Answers `501`: it creates the function but does not run its code | The Node server runs as a local process in CI. `test_web_function_endpoint_serves_our_code` is marked `xfail(strict=True)`, so it fails as soon as the emulator serves the code |
| `ListWebFunctionEndpoints` | Returns `NotImplemented` | The project uses `GetWebFunctionEndpoint` |
| `rawPath` in Function URL events | Includes the emulator's routing prefix `/_aws/lambda-url/<id>` | `functions/event/items_api.py` removes the prefix. On AWS the prefix never appears, so this line changes nothing there |

All the other checks are `supported` and pass on 1.0.522: DynamoDB table creation and conditional writes, S3 uploads, Web Function create and get (the function, its revision and its endpoint all reach `Active`), Lambda `CreateFunction` and `Invoke` with Python 3.13, and Function URLs. The emulator also returns `403` for a Function URL call when the function has no resource-based policy, like AWS does.

## Setting up the repository on GitHub

1. In **Settings → General → Pull Requests**, enable *Allow auto-merge*. The ruleset allows only squash merges.
2. Import the ruleset for `main`. With the GitHub CLI, run this from the repository folder (`gh` fills in `{owner}/{repo}` for you):
   ```bash
   gh api -X POST "repos/{owner}/{repo}/rulesets" --input .github/rulesets/main.json
   ```
   You can also use **Settings → Rules → Rulesets → New ruleset → Import a ruleset**. The ruleset requires a pull request (with no approvals needed), requires the `lint`, `unit` and `emulator` checks, and blocks force pushes and deletion of `main`. On a free GitHub account, rulesets are enforced only on public repositories.
3. For each change:
   ```bash
   git switch -c feature/my-change
   git commit -am "Describe the change"
   git push -u origin feature/my-change
   gh pr create --fill
   gh pr merge --auto --squash
   ```

## Running the pipeline on a Linux machine

`scripts/ci_local.sh` runs the same steps as `ci.yml`, in the same order. It also imitates `$GITHUB_ENV` with a file, so values exported by one step reach the next ones. It was tested on Ubuntu 24.04 x86_64 with Python 3.12.3 and Node 24.22.3; CI uses Python 3.13. You need Node 24 with npm, `curl`, and `sudo` to install the emulator package. `shellcheck` is optional: the script skips that step when it is not installed.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
bash scripts/ci_local.sh
```

To work by hand against the emulator:

```bash
bash scripts/emulator/install.sh    # EMULATOR_VERSION=1.0.522, or "latest" (the default)
bash scripts/emulator/start.sh      # starts it in the background on port 9297
. scripts/emulator/env.sh           # endpoint, credentials and CA for this run
python -m tools.capability_gate
python -m tools.deploy              # run "npm ci --omit=dev" in functions/web first
bash scripts/emulator/stop.sh
```

The emulator creates new credentials and a new CA certificate every time it starts, so load `env.sh` again after each `start.sh`. The emulator keeps all resources in memory and loses them when it stops. `env.sh` and `start.sh` remove real AWS credentials from the environment and disable the EC2 instance metadata service.

## Repository layout

```
functions/web/        Web Function (Node.js 24): src/app.js routing, src/repo.js DynamoDB, src/server.js entry point
functions/event/      Event Function (Python 3.13) for the Function URL
tools/                capability_gate.py, deploy.py, aws_helpers.py
scripts/emulator/     install.sh, start.sh, env.sh, stop.sh
scripts/              ci_local.sh, start_web_function_local.sh
tests/unit/           no emulator needed
tests/integration/    checks the resources that tools/deploy.py created
tests/e2e/            the HTTP contract, run against both targets
.github/workflows/    ci.yml (required checks) and nightly-emulator-latest.yml
.github/rulesets/     main.json, the ruleset for main
spike/FINDINGS.md     raw results of the first experiments with the emulator
```
