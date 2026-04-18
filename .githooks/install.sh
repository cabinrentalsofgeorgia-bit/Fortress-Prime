#!/usr/bin/env bash
# .githooks/install.sh — configure git to use repo-local hooks
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOKS_DIR="${REPO_ROOT}/.githooks"

git config core.hooksPath "${HOOKS_DIR}"
chmod +x "${HOOKS_DIR}/pre-commit"

echo "✓ Pre-commit secret hook installed."
echo ""
echo "Test it:"
echo "  echo 'password=\"badpass123\"' > /tmp/hook_test.txt"
echo "  git add /tmp/hook_test.txt && git commit -m 'test' # should block"
echo "  git reset HEAD /tmp/hook_test.txt && rm /tmp/hook_test.txt"
echo ""
echo "Bypass with: git commit --no-verify"
