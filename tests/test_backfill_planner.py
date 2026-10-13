from datetime import date

from mercado_financeiro.data.backfill import IngestionLane, plan_current_with_backfill


def test_current_ingestion_is_independent_from_historical_backfill():
    plan = plan_current_with_backfill(
        source="B3",
        dataset="COTAHIST",
        current_date=date(2026, 10, 7),
    )
    assert plan.current.lane is IngestionLane.CURRENT
    assert plan.current.start == date(2026, 10, 7)
    assert plan.backfill[0].start == date(2001, 1, 2)
    assert plan.backfill[-1].end == date(2026, 10, 6)
    assert all(window.end < plan.current.start for window in plan.backfill)


def test_initial_backfill_is_year_partitioned_without_gaps():
    plan = plan_current_with_backfill(
        source="CVM",
        dataset="FCA",
        current_date=date(2003, 1, 2),
    )
    assert [(w.start, w.end) for w in plan.backfill] == [
        (date(2001, 1, 2), date(2001, 12, 31)),
        (date(2002, 1, 1), date(2002, 12, 31)),
        (date(2003, 1, 1), date(2003, 1, 1)),
    ]
