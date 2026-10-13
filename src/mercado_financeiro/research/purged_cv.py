from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable

import pandas as pd

from .tournament import WalkForwardSplit, walk_forward_splits


@dataclass(frozen=True)
class PurgedWalkForwardFold:
    """One chronological fold after purging label-overlap leakage.

    ``train_indices`` and ``validation_indices`` contain only observations whose
    label-information intervals do not overlap the next out-of-sample window.
    Embargo gaps are supplied by the underlying chronological split.  The original
    dataframe index is preserved so downstream model code can select rows without
    reordering the research panel.
    """

    split: WalkForwardSplit
    train_indices: tuple[Hashable, ...]
    validation_indices: tuple[Hashable, ...]
    test_indices: tuple[Hashable, ...]
    purged_train_count: int
    purged_validation_count: int


def purged_walk_forward_splits(
    labels: pd.DataFrame,
    *,
    sample_time_column: str = "label_start",
    label_end_column: str = "label_end",
    train_periods: int,
    validation_periods: int,
    test_periods: int,
    embargo_periods: int = 0,
    step_periods: int | None = None,
) -> tuple[PurgedWalkForwardFold, ...]:
    """Build walk-forward folds with both embargo and outcome-horizon purging.

    Financial labels often span an interval (for example, a 21-session forward
    return).  A row whose label interval extends into validation or test leaks future
    information even when the feature timestamp itself is earlier.  This function
    removes such rows deterministically.

    Purging rules:
    - training labels overlapping the validation window are removed;
    - validation labels overlapping the test window are removed;
    - explicit chronological embargo gaps are still enforced by
      :func:`walk_forward_splits`.

    The test window is never used to decide which test rows remain.  No random split
    is performed.
    """

    required = {sample_time_column, label_end_column}
    missing = required - set(labels.columns)
    if missing:
        raise ValueError(f"missing label interval columns: {sorted(missing)}")
    if not labels.index.is_unique:
        raise ValueError("labels index must be unique so fold membership is auditable")

    frame = labels.copy()
    frame["__sample_start"] = pd.to_datetime(
        frame[sample_time_column], errors="coerce", utc=True
    )
    frame["__label_end"] = pd.to_datetime(
        frame[label_end_column], errors="coerce", utc=True
    )
    if frame[["__sample_start", "__label_end"]].isna().any().any():
        raise ValueError("label intervals must contain valid timestamps")
    if (frame["__label_end"] < frame["__sample_start"]).any():
        raise ValueError("label_end cannot precede sample time")

    base = walk_forward_splits(
        frame["__sample_start"],
        train_periods=train_periods,
        validation_periods=validation_periods,
        test_periods=test_periods,
        embargo_periods=embargo_periods,
        step_periods=step_periods,
    )

    folds: list[PurgedWalkForwardFold] = []
    for split in base:
        train_candidate = frame.loc[
            frame["__sample_start"].between(split.train_start, split.train_end, inclusive="both")
        ]
        validation_candidate = frame.loc[
            frame["__sample_start"].between(
                split.validation_start, split.validation_end, inclusive="both"
            )
        ]
        test_candidate = frame.loc[
            frame["__sample_start"].between(split.test_start, split.test_end, inclusive="both")
        ]

        # A label interval is inclusive at both ends.  If its end reaches the next
        # OOS window's first timestamp, the outcome uses information from that OOS
        # period and must therefore be purged.
        train = train_candidate.loc[
            train_candidate["__label_end"] < split.validation_start
        ]
        validation = validation_candidate.loc[
            validation_candidate["__label_end"] < split.test_start
        ]

        folds.append(
            PurgedWalkForwardFold(
                split=split,
                train_indices=tuple(train.index),
                validation_indices=tuple(validation.index),
                test_indices=tuple(test_candidate.index),
                purged_train_count=len(train_candidate) - len(train),
                purged_validation_count=len(validation_candidate) - len(validation),
            )
        )
    return tuple(folds)
