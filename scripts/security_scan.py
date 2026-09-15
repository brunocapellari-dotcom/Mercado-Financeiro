from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys

FORBIDDEN_SUFFIXES = {
    ".pem",
    ".p12",
    ".pfx",
    ".key",
    ".sqlite",
    ".sqlite3",
    ".duckdb",
    ".parquet",
    ".feather",
}
FORBIDDEN_NAMES = {".env", "credentials.json", "service-account.json", "id_rsa", "id_ed25519"}
BINARY_DATA_SUFFIXES = {".zip", ".7z", ".rar"}
ALLOW_BINARY_PREFIXES = ("tests/fixtures/",)
SKIP_CONTENT_SCAN = {"scripts/security_scan.py"}

PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github_pat": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    "openai_style_secret": re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b"),
}


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
    )
    return [Path(p.decode("utf-8")) for p in result.stdout.split(b"\0") if p]


def main() -> int:
    failures: list[str] = []
    for path in tracked_files():
        posix = path.as_posix()
        lower_name = path.name.lower()
        suffix = path.suffix.lower()
        if lower_name in FORBIDDEN_NAMES or suffix in FORBIDDEN_SUFFIXES:
            failures.append(f"forbidden sensitive/data file tracked: {posix}")
        if suffix in BINARY_DATA_SUFFIXES and not posix.startswith(ALLOW_BINARY_PREFIXES):
            failures.append(f"archive must not be committed outside test fixtures: {posix}")
        if posix in SKIP_CONTENT_SCAN or not path.is_file():
            continue
        try:
            raw = path.read_bytes()
            if b"\x00" in raw:
                continue
            text = raw.decode("utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name, pattern in PATTERNS.items():
            if pattern.search(text):
                failures.append(f"possible {name} found in tracked file: {posix}")
    if failures:
        print("SECURITY_SCAN_FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("SECURITY_SCAN_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
