from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import io
import urllib.error
import zipfile

from mercado_financeiro.security import DownloadPolicy, SourceSecurityError, download_https, validate_zip_bytes

URL = "https://www.b3.com.br/pesquisapregao/download?filelist=IN{stamp}.zip"
TEST_DATES = (
    date(2015, 12, 30),
    date(2016, 1, 4),
    date(2016, 1, 14),
    date(2016, 1, 15),
    date(2016, 1, 18),
    date(2016, 2, 1),
    date(2017, 1, 2),
    date(2018, 1, 2),
    date(2021, 4, 23),
)


@dataclass(frozen=True)
class Result:
    refdate: date
    status: str
    bytes: int = 0
    sha256: str | None = None
    members: tuple[str, ...] = ()
    error: str | None = None


def audit_date(refdate: date) -> Result:
    url = URL.format(stamp=refdate.strftime("%y%m%d"))
    policy = DownloadPolicy(max_bytes=350_000_000, timeout_seconds=95.0)
    try:
        payload = download_https(url, policy)
        if not payload:
            return Result(refdate, "empty")
        validate_zip_bytes(
            payload,
            max_members=50,
            max_total_uncompressed=2_500_000_000,
            max_member_uncompressed=2_000_000_000,
            max_compression_ratio=300.0,
        )
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = tuple(info.filename for info in archive.infolist())
        if not members:
            return Result(refdate, "empty_zip", bytes=len(payload))
        digest = hashlib.sha256(payload).hexdigest()
        return Result(refdate, "available", len(payload), digest, members[:5])
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, SourceSecurityError, ValueError, OSError) as exc:
        return Result(refdate, "unavailable_or_error", error=f"{type(exc).__name__}: {exc}")


def main() -> None:
    results = [audit_date(refdate) for refdate in TEST_DATES]
    for result in results:
        print(
            "BVBG028_HISTORY "
            f"refdate={result.refdate.isoformat()} status={result.status} bytes={result.bytes} "
            f"sha256={result.sha256} members={list(result.members)} error={result.error!r}"
        )
    available = [result for result in results if result.status == "available"]
    if available:
        print(f"BVBG028_EARLIEST_TESTED_AVAILABLE refdate={min(r.refdate for r in available).isoformat()}")
    else:
        print("BVBG028_EARLIEST_TESTED_AVAILABLE refdate=NONE")


if __name__ == "__main__":
    main()
