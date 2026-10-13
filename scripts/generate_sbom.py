from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/gate/sbom.cdx.json")
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "cyclonedx_py",
        "environment",
        sys.executable,
        "--spec-version",
        "1.6",
        "--output-format",
        "JSON",
        "--output-reproducible",
        "--pyproject",
        "pyproject.toml",
        "--output-file",
        str(output),
    ]
    subprocess.run(command, check=True)
    payload = json.loads(output.read_text(encoding="utf-8"))
    if payload.get("bomFormat") != "CycloneDX":
        raise RuntimeError("SBOM output is not CycloneDX")
    components = payload.get("components")
    if not isinstance(components, list) or not components:
        raise RuntimeError("SBOM contains no components")
    print(f"SBOM_OK path={output} components={len(components)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
