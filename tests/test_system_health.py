from datetime import datetime, timedelta, timezone

from mercado_financeiro.observability.health import (
    HealthState,
    build_system_health,
    evaluate_freshness_health,
)


def test_system_health_surfaces_stale_jobs_and_failed_sources():
    now = datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc)
    stale = evaluate_freshness_health(
        component="cotahist-current",
        category="dataset",
        checked_at=now,
        last_success_at=now - timedelta(days=2),
        max_age=timedelta(days=1),
    )
    failed = evaluate_freshness_health(
        component="paper-cycle",
        category="job",
        checked_at=now,
        last_success_at=now - timedelta(hours=1),
        max_age=timedelta(hours=2),
        failed=True,
        details="job failed",
    )
    report = build_system_health([stale, failed], checked_at=now)
    assert stale.state is HealthState.DEGRADED
    assert report.state is HealthState.FAILED
    assert report.failed == ("paper-cycle",)
    assert report.degraded == ("cotahist-current",)
