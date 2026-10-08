from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Literal
import pandas as pd

_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")
Dialect = Literal["duckdb", "bigquery"]

def _id(value: str) -> str:
    text = str(value).strip()
    if not _ID.fullmatch(text):
        raise ValueError(f"unsafe identifier: {value!r}")
    return text

@dataclass(frozen=True)
class AsOfQuerySpec:
    table: str
    partition_by: tuple[str, ...]
    available_from: str = "available_from"
    tie_breakers: tuple[str, ...] = ()
    def __post_init__(self) -> None:
        _id(self.table)
        if not self.partition_by:
            raise ValueError("partition_by cannot be empty")
        for value in (*self.partition_by, self.available_from, *self.tie_breakers):
            _id(value)

def compile_latest_asof_sql(spec: AsOfQuerySpec, *, dialect: Dialect) -> str:
    if dialect not in {"duckdb", "bigquery"}:
        raise ValueError("unsupported SQL dialect")
    quote = lambda v: f'"{_id(v)}"' if dialect == "duckdb" else f'`{_id(v)}`'
    parameter = "?" if dialect == "duckdb" else "@cutoff"
    partition = ", ".join(quote(v) for v in spec.partition_by)
    ordering = [f"{quote(spec.available_from)} DESC", *(f"{quote(v)} DESC" for v in spec.tie_breakers)]
    # All identifiers are restricted by _id(); cutoff remains a bound parameter.
    return (  # nosec B608
        "SELECT * FROM " + quote(spec.table) + " WHERE " + quote(spec.available_from)  # nosec B608
        + f" <= {parameter} QUALIFY ROW_NUMBER() OVER (PARTITION BY "
        + partition + " ORDER BY " + ", ".join(ordering) + ") = 1"
    )

def latest_known_asof(
    frame: pd.DataFrame,
    cutoff: str | pd.Timestamp,
    *,
    partition_by: Iterable[str],
    available_from: str = "available_from",
    tie_breakers: Iterable[str] = (),
) -> pd.DataFrame:
    keys = tuple(_id(v) for v in partition_by)
    if not keys:
        raise ValueError("partition_by cannot be empty")
    available_from = _id(available_from)
    ties = tuple(_id(v) for v in tie_breakers)
    missing = set((*keys, available_from, *ties)) - set(frame.columns)
    if missing:
        raise ValueError(f"missing PIT columns: {sorted(missing)}")
    cutoff_ts = pd.to_datetime(cutoff, errors="raise", utc=True)
    out = frame.copy()
    out[available_from] = pd.to_datetime(out[available_from], errors="coerce", utc=True)
    if out[available_from].isna().any():
        raise ValueError("available_from contains invalid values")
    eligible = out.loc[out[available_from] <= cutoff_ts].copy()
    if eligible.empty:
        return eligible
    eligible = eligible.sort_values([*keys, available_from, *ties], kind="stable")
    return eligible.groupby(list(keys), sort=False, as_index=False).tail(1).reset_index(drop=True)
