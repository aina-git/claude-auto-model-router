#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
claude plugin marketplace add "$REPO_DIR" || claude plugin marketplace update abiodun-tools
claude plugin uninstall auto-model-router@abiodun-tools >/dev/null 2>&1 || true
claude plugin install auto-model-router@abiodun-tools
claude plugin enable auto-model-router@abiodun-tools >/dev/null 2>&1 || true
claude plugin list | grep -A4 "auto-model-router"
