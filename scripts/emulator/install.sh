#!/usr/bin/env bash
# Installs AWS Emulator as a native Debian package (Ubuntu runners, no Docker).
# EMULATOR_VERSION: a version such as 1.0.522, or "latest".
set -euo pipefail
VERSION="${EMULATOR_VERSION:-latest}"
ARCH=$(dpkg --print-architecture)   # amd64 | arm64
BASE=https://downloads.aws.com/aws-emulator/packages/aws-emulator/LTS

if [ "$VERSION" = latest ]; then
  URL="$BASE/latest/aws-emulator_${ARCH}.deb"
else
  URL="$BASE/aws-emulator_${VERSION}-1_${ARCH}.deb"
fi

if command -v aws-emulator >/dev/null && [ "$VERSION" != latest ] \
   && aws-emulator -v | grep -q "Version: ${VERSION}$"; then
  echo "aws-emulator ${VERSION} already installed"
else
  echo "downloading $URL"
  curl -fsSLo /tmp/aws-emulator.deb "$URL"
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --allow-downgrades /tmp/aws-emulator.deb >/dev/null
fi

INSTALLED=$(aws-emulator -v | awk '/^Version:/ {print $2}')
aws-emulator -v
if [ -n "${GITHUB_ENV:-}" ]; then echo "EMULATOR_VERSION_INSTALLED=${INSTALLED}" >> "$GITHUB_ENV"; fi
