#!/usr/bin/env python3
"""Pre-commit guard: refuse staged files containing secrets, private words, or
large dollar figures. Wordlist: $HOMEAI_PRIVATE_DIR/wordlist.txt (default private/wordlist.txt).
Exit 1 on any hit."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

KEY_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}"), re.compile(r"sk-(live|test|proj)-[A-Za-z0-9_-]{10,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"), re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"), re.compile(r"-----BEGIN (RSA|EC|OPENSSH) PRIVATE KEY-----"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{24,}"),
    re.compile(r"\b(xpub|ypub|zpub)[1-9A-HJ-NP-Za-km-z]{40,}"),
]
MONEY = re.compile(r"\$\s?\d{2,3},\d{3}(,\d{3})*|\$\s?\d{5,}")
ALLOW = {"config.example.yaml", "README.md"}  # examples may contain sample figures


def staged_files() -> list[Path]:
    out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"], capture_output=True, text=True)
    return [Path(p) for p in out.stdout.split() if Path(p).is_file()]


def main() -> int:
    priv = Path(os.environ.get("HOMEAI_PRIVATE_DIR", "private"))
    words = [w.strip() for w in (priv / "wordlist.txt").read_text().splitlines()
             if w.strip() and not w.startswith("#")] if (priv / "wordlist.txt").exists() else []
    hits = []
    for f in staged_files():
        if f.parts and f.parts[0] == "private":
            hits.append((f, 0, "private/ must never be staged"))
            continue
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for pat in KEY_PATTERNS:
                if pat.search(line):
                    hits.append((f, i, f"secret pattern {pat.pattern[:30]}"))
            if f.name not in ALLOW and MONEY.search(line) and "test" not in str(f):
                hits.append((f, i, "dollar figure"))
            low = line.lower()
            for w in words:
                if w.lower() in low:
                    hits.append((f, i, f"private word '{w}'"))
    for f, i, why in hits:
        print(f"BLOCKED {f}:{i}: {why}")
    if hits:
        print(f"\n{len(hits)} problem(s). Move personal data to the private overlay or fix the line.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
