"""Check tracked source for generated files, local paths, and credential-like strings."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BANNED = {"node_modules", "__pycache__", ".venv", "venv", ".pytest_cache", "dist", "build", ".artifacts"}
PATTERNS = [
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("model API key", re.compile(r"\bsk-(?:(?:or-v1|proj|ant)-)?[A-Za-z0-9_-]{32,}\b")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("local user path", re.compile(r"[A-Za-z]:[\\/]Users[\\/][A-Za-z0-9_]+")),
]


def main():
    result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    paths = [Path(path.decode("utf-8")) for path in result.stdout.split(b"\0") if path]
    problems = []
    if not paths:
        print("No tracked files found. Run git add . before checking.", file=sys.stderr)
        return 1
    for relative in paths:
        if BANNED.intersection(relative.parts) or (relative.name.startswith(".env") and relative.name != ".env.example"):
            problems.append(f"{relative.as_posix()}: generated or private file")
            continue
        source = ROOT / relative
        if not source.is_file():
            problems.append(f"{relative.as_posix()}: tracked file is missing")
            continue
        raw = source.read_bytes()
        if b"\0" in raw:
            continue
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for label, pattern in PATTERNS:
                if pattern.search(line):
                    problems.append(f"{relative.as_posix()}:{number}: {label}")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print(f"Repository check passed: {len(paths)} tracked files; no forbidden paths or credential-like strings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
