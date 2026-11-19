#!/usr/bin/env bash
# Runs the same steps as .github/workflows/ci.yml on a Linux box (e.g. a devbox), in order.
# $GITHUB_ENV is emulated with a file that is re-read between steps, as Actions does.
# Prereqs: python3 (venv with requirements-dev.txt active), node 24, npm, curl, sudo for the install step.
set -euo pipefail
cd "$(dirname "$0")/.."
export EMULATOR_VERSION="${EMULATOR_VERSION:-1.0.522}"
mkdir -p .emulator reports
GITHUB_ENV="$PWD/.emulator/github_env"
export GITHUB_ENV
: > "$GITHUB_ENV"

step() {
  echo; echo "=== $1"
  shift
  set -a
  # shellcheck disable=SC1090
  . "$GITHUB_ENV"
  set +a
  "$@"
}

cleanup() {
  if [ -f .emulator/web-function.pid ]; then kill "$(cat .emulator/web-function.pid)" 2>/dev/null || true; fi
  bash scripts/emulator/stop.sh
}
trap cleanup EXIT

step "lint: ruff"            ruff check .
step "lint: ruff format"     ruff format --check .
check_js() { for f in functions/web/src/*.js functions/web/test/*.js; do node --check "$f"; done; }
step "lint: node --check"    check_js
if command -v shellcheck >/dev/null; then
  step "lint: shellcheck"    shellcheck scripts/*.sh scripts/emulator/*.sh
fi
step "unit: pytest"          pytest tests/unit -q
step "unit: node --test"     bash -c 'cd functions/web && npm ci --silent && npm test --silent'
step "build web package"     bash -c 'cd functions/web && npm ci --omit=dev --silent'
step "install emulator"      bash scripts/emulator/install.sh
step "start emulator"        bash scripts/emulator/start.sh
step "env"                   bash scripts/emulator/env.sh
step "capability gate"       python -m tools.capability_gate
step "deploy"                python -m tools.deploy
step "start web fn locally"  bash scripts/start_web_function_local.sh
step "integration + e2e"     pytest tests/integration tests/e2e -v --junitxml=reports/emulator.xml
step "test report"           python -m tools.junit_summary reports/emulator.xml --title "Emulator tests" --targets web-function,function-url
echo; echo "=== all steps passed"
