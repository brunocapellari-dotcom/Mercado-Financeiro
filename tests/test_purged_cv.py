import pandas as pd
import pytest

from mercado_financeiro.research import purged_walk_forward_splits


def test_purged_walk_forward_removes_label_overlap_from_train_and_validation():
    starts = pd.date_range("2026-01-01", periods=30, freq="D", tz="UTC")
    labels = pd.DataFrame(
        {
            "label_start": starts,
            "label_end": starts + pd.Timedelta(days=3),
        }
    )
    folds = purged_walk_forward_splits(
        labels,
        train_periods=10,
        validation_periods=5,
        test_periods=5,
        embargo_periods=1,
    )
    assert folds
    fold = folds[0]
    assert fold.purged_train_count == 2
    assert fold.purged_validation_count == 2

    retained_train = labels.loc[list(fold.train_indices)]
    retained_validation = labels.loc[list(fold.validation_indices)]
    assert (retained_train["label_end"] < fold.split.validation_start).all()
    assert (retained_validation["label_end"] < fold.split.test_start).all()
    assert fold.split.train_end < fold.split.validation_start < fold.split.test_start


def test_purged_walk_forward_preserves_original_row_indices():
    starts = pd.date_range("2026-01-01", periods=24, freq="D", tz="UTC")
    labels = pd.DataFrame(
        {"label_start": starts, "label_end": starts},
        index=[f"row-{i}" for i in range(len(starts))],
    )
    fold = purged_walk_forward_splits(
        labels,
        train_periods=8,
        validation_periods=4,
        test_periods=4,
        embargo_periods=1,
    )[0]
    assert fold.train_indices[0] == "row-0"
    assert all(index in labels.index for index in fold.test_indices)


def test_purged_walk_forward_rejects_invalid_intervals_and_duplicate_index():
    bad = pd.DataFrame(
        {
            "label_start": pd.to_datetime(["2026-01-02"], utc=True),
            "label_end": pd.to_datetime(["2026-01-01"], utc=True),
        }
    )
    with pytest.raises(ValueError, match="label_end cannot precede"):
        purged_walk_forward_splits(
            bad,
            train_periods=1,
            validation_periods=1,
            test_periods=1,
        )

    duplicate = pd.DataFrame(
        {
            "label_start": pd.date_range("2026-01-01", periods=3, freq="D", tz="UTC"),
            "label_end": pd.date_range("2026-01-01", periods=3, freq="D", tz="UTC"),
        },
        index=[0, 0, 1],
    )
    with pytest.raises(ValueError, match="index must be unique"):
        purged_walk_forward_splits(
            duplicate,
            train_periods=1,
            validation_periods=1,
            test_periods=1,
        )
