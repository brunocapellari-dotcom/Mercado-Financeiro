from __future__ import annotations

from pathlib import Path
import re
import sys


FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
ACTION = re.compile(r"^\s*-?\s*uses:\s*([^\s@]+)@([^\s#]+)")
CLOUDBUILD_IMAGE = re.compile(r"^\s*name:\s*([^\s#]+)")
UNTRUSTED_RUN_EXPR = re.compile(r"\$\{\{\s*github\.event\.(?:issue|pull_request|comment)")


def scan_workflow(path: Path) -> list[str]:
    failures: list[str] = []
    text = path.read_text(encoding="utf-8")
    if "pull_request_target:" in text:
        failures.append(f"{path}: pull_request_target is forbidden")
    if re.search(r"(?m)^permissions:\s*write-all\s*$", text):
        failures.append(f"{path}: write-all permissions are forbidden")
    if re.search(r"(?mi)^\s*persist-credentials:\s*true\s*$", text):
        failures.append(f"{path}: checkout credentials must not persist")
    if re.search(r"(?i)(curl|wget)[^\n|]*\|\s*(?:ba)?sh\b", text):
        failures.append(f"{path}: remote shell pipe is forbidden")
    if UNTRUSTED_RUN_EXPR.search(text):
        failures.append(f"{path}: untrusted event text may not be interpolated into run blocks")
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = ACTION.match(line)
        if not match:
            continue
        action, revision = match.groups()
        if action.startswith("./"):
            continue
        if not FULL_SHA.fullmatch(revision):
            failures.append(
                f"{path}:{lineno}: external action must be pinned to a full commit SHA"
            )
    return failures


def scan_cloudbuild(path: Path) -> list[str]:
    failures: list[str] = []
    text = path.read_text(encoding="utf-8")
    if re.search(r"(?i)(curl|wget)[^\n|]*\|\s*(?:ba)?sh\b", text):
        failures.append(f"{path}: remote shell pipe is forbidden")
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = CLOUDBUILD_IMAGE.match(line)
        if not match:
            continue
        image = match.group(1).strip("'\"")
        if "@sha256:" not in image:
            failures.append(
                f"{path}:{lineno}: build image must be pinned by sha256 digest"
            )
    return failures


def main() -> int:
    failures: list[str] = []
    for path in sorted(Path(".github/workflows").glob("*.y*ml")):
        failures.extend(scan_workflow(path))
    for cloudbuild in sorted(Path(".").glob("cloudbuild*.yaml")):
        if cloudbuild.is_file():
            failures.extend(scan_cloudbuild(cloudbuild))
    if failures:
        print("WORKFLOW_SECURITY_SCAN_FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("WORKFLOW_SECURITY_SCAN_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
