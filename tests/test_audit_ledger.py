from datetime import datetime, timezone

from mercado_financeiro.architecture import AuditDomain
from mercado_financeiro.audit import AuditLedger


def test_audit_ledger_hash_chain_is_verifiable():
    ledger = AuditLedger()
    first = ledger.append(
        domain=AuditDomain.MARKET_DATA,
        status="pass",
        run_id="run-1",
        commit_sha="abc123",
        source="B3",
        version="1",
        metrics={"rows": 100},
        timestamp_utc=datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc),
    )
    second = ledger.append(
        domain=AuditDomain.RECONCILIATION,
        status="pass",
        run_id="run-2",
        commit_sha="def456",
        source="broker",
        version="1",
        metrics={"mismatches": 0},
        timestamp_utc=datetime(2026, 9, 15, 12, 1, tzinfo=timezone.utc),
    )

    assert first.record_hash is not None
    assert second.previous_hash == first.record_hash
    assert ledger.verify_chain() is True
