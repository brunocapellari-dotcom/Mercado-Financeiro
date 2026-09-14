from __future__ import annotations

import csv
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import urllib.request
import zipfile

BASE_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_{year}.zip"
YEARS = range(2010, 2027)
INTERESTING_SAMPLE_TOKENS = (
    "cnpj",
    "codigo",
    "negoci",
    "ticker",
    "valor_mobiliario",
    "versao",
    "id_doc",
    "dt_receb",
    "data",
)


def _download(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mercado-Financeiro-PIT-Audit/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # nosec B310: fixed CVM host
        return response.read()


def _target_kind(basename: str, year: int) -> str | None:
    lowered = basename.lower()
    if lowered == f"fca_cia_aberta_{year}.csv":
        return "ledger"
    if lowered.startswith("fca_cia_aberta_geral_"):
        return "geral"
    if lowered.startswith("fca_cia_aberta_valor_mobiliario_"):
        return "valor_mobiliario"
    return None


def _compact_sample(row: dict[str, str | None]) -> dict[str, str | None]:
    return {
        key: value
        for key, value in row.items()
        if any(token in key.lower() for token in INTERESTING_SAMPLE_TOKENS)
    }


def _inspect_csv(raw: bytes) -> dict[str, object]:
    encoding = ""
    for candidate in ("utf-8-sig", "latin-1"):
        try:
            text = raw.decode(candidate)
            encoding = candidate
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
        if len(sample_rows) < 2:
            sample_rows.append(_compact_sample(dict(row)))

    return {
        "encoding": encoding,
        "columns": reader.fieldnames or [],
        "sample_rows": sample_rows,
        "row_count": row_count,
    }


def _print_schema(year: int, kind: str, member: str, result: dict[str, object]) -> None:
    columns = result["columns"]
    samples = result["sample_rows"]
    print(
        "FCA_SCHEMA "
        f"year={year} kind={kind} member={member} rows={result['row_count']} "
        f"columns={json.dumps(columns, ensure_ascii=False)}"
    )
    print(
        "FCA_SAMPLE "
        f"year={year} kind={kind} values={json.dumps(samples, ensure_ascii=False)}"
    )


def main() -> None:
    output: dict[str, object] = {
        "source": "CVM FCA",
        "base_url": BASE_URL,
        "years": {},
    }
    years_output: dict[str, dict[str, object]] = {}
    output["years"] = years_output

    print("FCA_SCHEMA_AUDIT_START")
    for year in YEARS:
        url = BASE_URL.format(year=year)
        year_result: dict[str, object] = {"url": url}
        try:
            payload = _download(url)
            digest = sha256(payload).hexdigest()
            year_result["sha256"] = digest
            year_result["bytes"] = len(payload)
            print(f"FCA_ZIP year={year} bytes={len(payload)} sha256={digest}")
            with zipfile.ZipFile(BytesIO(payload)) as archive:
                members = archive.namelist()
                year_result["members"] = members
                inspected: dict[str, object] = {}
                kinds_seen: set[str] = set()
                for member in members:
                    kind = _target_kind(Path(member).name, year)
                    if kind is None:
                        continue
                    result = _inspect_csv(archive.read(member))
                    inspected[member] = result
                    kinds_seen.add(kind)
                    _print_schema(year, kind, member, result)
                required = {"ledger", "geral", "valor_mobiliario"}
                missing = required - kinds_seen
                if missing:
                    raise ValueError(f"missing expected FCA members: {sorted(missing)}")
                year_result["inspected"] = inspected
                year_result["status"] = "ok"
        except Exception as exc:  # audit must report gaps instead of hiding them
            year_result["status"] = "error"
            year_result["error"] = f"{type(exc).__name__}: {exc}"
            print(f"FCA_ERROR year={year} error={year_result['error']}")
        years_output[str(year)] = year_result

    out_dir = Path("artifacts")
    out_dir.mkdir(exist_ok=True)
    target = out_dir / "fca_schema_audit.json"
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    failures = [year for year, result in years_output.items() if result["status"] != "ok"]
    print("FCA_SCHEMA_AUDIT_END")
    if failures:
        raise SystemExit(f"FCA audit failed for years: {failures}")


if __name__ == "__main__":
    main()
