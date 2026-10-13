from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import subprocess
import sys


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def _timestamp() -> str | None:
    raw = os.getenv("SOURCE_DATE_EPOCH")
    if raw is None:
        return None
    value = int(raw)
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sbom", default="artifacts/gate/sbom.cdx.json")
    parser.add_argument("--output", default="artifacts/gate/provenance.json")
    args = parser.parse_args()
    sbom = Path(args.sbom)
    if not sbom.is_file():
        raise FileNotFoundError(f"SBOM not found: {sbom}")
    sbom_bytes = sbom.read_bytes()
    commit = os.getenv("COMMIT_SHA", "").strip() or _git_head()
    if len(commit) != 40 or any(ch not in "0123456789abcdefABCDEF" for ch in commit):
        raise RuntimeError("build provenance requires a full 40-character commit SHA")

    payload = {
        "schema": "mercado-financeiro-build-provenance-v1",
        "source_commit_sha": commit.lower(),
        "sbom_sha256": sha256(sbom_bytes).hexdigest(),
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "source_date_epoch_utc": _timestamp(),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(f"BUILD_PROVENANCE_OK path={output} commit={payload['source_commit_sha']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
