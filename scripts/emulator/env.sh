# shellcheck shell=bash
# Points the AWS CLI and SDKs (Python, Node.js) at a running AWS Emulator.
#   local:           . scripts/emulator/env.sh
#   GitHub Actions:  bash scripts/emulator/env.sh   (also appends the variables to $GITHUB_ENV)
# Credentials and the CA are regenerated at every emulator start, so run this after start.sh.
_EMU_PORT="${EMULATOR_PORT:-9297}"
_EMU_DIR="$HOME/.aws/emulator/${_EMU_PORT}"

unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_PROFILE

_emu_vars=(
  "AWS_ENDPOINT_URL=https://127.0.0.1:${_EMU_PORT}"
  "AWS_CONFIG_FILE=${_EMU_DIR}/config"
  "AWS_SHARED_CREDENTIALS_FILE=${_EMU_DIR}/emulator_credentials"
  "AWS_CA_BUNDLE=${_EMU_DIR}/ca.pem"
  "NODE_EXTRA_CA_CERTS=${_EMU_DIR}/ca.pem"
  "AWS_EC2_METADATA_DISABLED=true"
  "AWS_DISABLE_HOST_PREFIX_INJECTION=true"
  "AWS_REGION=us-east-1"
  "AWS_DEFAULT_REGION=us-east-1"
)
for _kv in "${_emu_vars[@]}"; do
  export "${_kv?}"
  if [ -n "${GITHUB_ENV:-}" ]; then echo "$_kv" >> "$GITHUB_ENV"; fi
done
unset _kv _emu_vars _EMU_DIR _EMU_PORT
