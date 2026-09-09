#!/usr/bin/env bash
# Install the pre-commit guard (private words + secrets; gitleaks too if installed).
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
HOOK="$ROOT/.git/hooks/pre-commit"
cat > "$HOOK" <<'EOF'
#!/usr/bin/env bash
set -e
ROOT="$(git rev-parse --show-toplevel)"
python3 "$ROOT/scripts/check_private_words.py"
if command -v gitleaks >/dev/null 2>&1; then
  gitleaks protect --staged --redact -v
fi
EOF
chmod +x "$HOOK"
echo "installed $HOOK"
