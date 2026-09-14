from __future__ import annotations

import csv
from hashlib import sha256
from io import BytesIO, TextIOWrapper
import json
from pathlib import Path
import urllib.request
import zipfile

BASE_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_{year}.zip"
YEARS = range(2010, 2027)
TARGET_PREFIXES = (
    "fca_cia_aberta_geral_",
    "fca_cia_aberta_valor_mobiliario_",
)


def _download(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mercado-Financeiro-PIT-Audit/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # nosec B310: fixed CVM host
        return response.read()


def _inspect_csv(raw: bytes) -> dict[str, object]:
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("could not decode CVM CSV")

    lines = text.splitlines()
    if not lines:
        return {"encoding": encoding, "columns": [], "sample_rows": [], "row_count": 0}

    reader = csv.DictReader(lines, delimiter=";")
    sample_rows: list[dict[str, str | None]] = []
    row_count = 0
    for row in reader:
        row_count += 1
        if len(sample_rows) < 3:
            sample_rows.append(dict(row))

    return {
        "encoding": encoding,
        "columns": reader.fieldnames or [],
        "sample_rows": sample_rows,
        "row_count": row_count,
    }


def main() -> None:
    output: dict[str, object] = {
        "source": "CVM FCA",
        "base_url": BASE_URL,
        "years": {},
    }

    for year in YEARS:
        url = BASE_URL.format(year=year)
        year_result: dict[str, object] = {"url": url}
        try:
            payload = _download(url)
            year_result["sha256"] = sha256(payload).hexdigest()
            year_result["bytes"] = len(payload)
            with zipfile.ZipFile(BytesIO(payload)) as archive:
                members = archive.namelist()
                year_result["members"] = members
                inspected: dict[str, object] = {}
                for member in members:
                    basename = Path(member).name.lower()
                    if any(basename.startswith(prefix) for prefix in TARGET_PREFIXES):
                        inspected[member] = _inspect_csv(archive.read(member))
                year_result["inspected"] = inspected
                year_result["status"] = "ok"
        except Exception as exc:  # audit must report gaps instead of hiding them
            year_result["status"] = "error"
            year_result["error"] = f"{type(exc).__name__}: {exc}"
        output["years"][str(year)] = year_result

    out_dir = Path("artifacts")
    out_dir.mkdir(exist_ok=True)
    target = out_dir / "fca_schema_audit.json"
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    failures = [year for year, result in output["years"].items() if result["status"] != "ok"]
    if failures:
        raise SystemExit(f"FCA audit failed for years: {failures}")


if __name__ == "__main__":
    main()
