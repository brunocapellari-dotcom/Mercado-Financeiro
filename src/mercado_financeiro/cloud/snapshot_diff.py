from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
import pandas as pd

@dataclass(frozen=True)
class SnapshotDiff:
    previous_rows: int
    current_rows: int
    row_delta: int
    added_columns: tuple[str, ...]
    removed_columns: tuple[str, ...]
    added_keys: int
    removed_keys: int
    changed_rows: int
    duplicate_current_keys: int

def compare_snapshots(previous: pd.DataFrame, current: pd.DataFrame, *, keys: Iterable[str]) -> SnapshotDiff:
    key_columns = tuple(str(key) for key in keys)
    if not key_columns:
        raise ValueError("snapshot diff requires keys")
    missing = set(key_columns) - (set(previous.columns) & set(current.columns))
    if missing:
        raise ValueError(f"snapshot diff keys missing: {sorted(missing)}")
    prev_keys = previous[list(key_columns)].astype(str).agg("\x1f".join, axis=1)
    curr_keys = current[list(key_columns)].astype(str).agg("\x1f".join, axis=1)
    duplicate_current = int(curr_keys.duplicated().sum())
    shared = [c for c in previous.columns if c in current.columns and c not in key_columns]
    prev_indexed = previous.assign(__key=prev_keys).set_index("__key")
    curr_indexed = current.assign(__key=curr_keys).set_index("__key")
    common = prev_indexed.index.intersection(curr_indexed.index)
    changed = 0
    if shared and len(common):
        left = prev_indexed.loc[common, shared].astype("string").fillna("<NA>")
        right = curr_indexed.loc[common, shared].astype("string").fillna("<NA>")
        changed = int(left.ne(right).any(axis=1).sum())
    prev_set, curr_set = set(prev_keys), set(curr_keys)
    return SnapshotDiff(
        len(previous), len(current), len(current) - len(previous),
        tuple(sorted(set(current.columns) - set(previous.columns))),
        tuple(sorted(set(previous.columns) - set(current.columns))),
        len(curr_set - prev_set), len(prev_set - curr_set), changed, duplicate_current,
    )
