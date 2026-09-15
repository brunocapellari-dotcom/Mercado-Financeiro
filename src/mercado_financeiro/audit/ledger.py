from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from threading import RLock
from typing import Protocol

from mercado_financeiro.architecture import AuditDomain


@dataclass(frozen=True)
class AuditRecord:
    domain: AuditDomain
    status: str
    run_id: str
    commit_sha: str
    source: str
    version: str
    timestamp_utc: datetime
    metrics: dict[str, object]
    violations: tuple[str, ...] = ()
    artifact_uri: str | None = None
    previous_hash: str | None = None
    record_hash: str | None = None


class AuditSink(Protocol):
    """Persistence boundary for tamper-evident audit records.

    Live implementations must persist externally in an append-only/WORM-capable
    system and must not grant the execution identity delete/update authority.
    """

    live_safe: bool

    def append_record(self, record: AuditRecord) -> None:
        ...


class AuditLedger:
    """Thread-safe in-memory hash-chained audit ledger for tests/paper.

    The hash chain makes tampering detectable, but memory is not durable or
    immutable storage. Live startup must therefore reject this implementation.
    """

    live_safe = False

    def __init__(self, *, sink: AuditSink | None = None) -> None:
        self._records: list[AuditRecord] = []
        self._sink = sink
        self._lock = RLock()

    @property
    def records(self) -> tuple[AuditRecord, ...]:
        with self._lock:
            return tuple(self._records)

    @property
    def external_sink_live_safe(self) -> bool:
        return bool(self._sink is not None and getattr(self._sink, "live_safe", False))

    def append(
        self,
        *,
        domain: AuditDomain,
        status: str,
        run_id: str,
        commit_sha: str,
        source: str,
        version: str,
        metrics: dict[str, object],
        violations: tuple[str, ...] = (),
        artifact_uri: str | None = None,
        timestamp_utc: datetime | None = None,
    ) -> AuditRecord:
        ts = timestamp_utc or datetime.now(timezone.utc)
        if ts.tzinfo is None or ts.utcoffset() is None:
            raise ValueError("timestamp_utc must be timezone-aware")
        ts = ts.astimezone(timezone.utc)
        with self._lock:
            previous_hash = self._records[-1].record_hash if self._records else None
            base = AuditRecord(
                domain=domain,
                status=status,
                run_id=run_id,
                commit_sha=commit_sha,
                source=source,
                version=version,
                timestamp_utc=ts,
                metrics=metrics,
                violations=violations,
                artifact_uri=artifact_uri,
                previous_hash=previous_hash,
            )
            digest = self._hash_record(base)
            record = AuditRecord(**{**asdict(base), "domain": domain, "record_hash": digest})
            if self._sink is not None:
                # Persist the immutable external copy before accepting the local
                # append. A sink error therefore fails closed.
                self._sink.append_record(record)
            self._records.append(record)
            return record

    def verify_chain(self) -> bool:
        with self._lock:
            previous: str | None = None
            for record in self._records:
                if record.previous_hash != previous:
                    return False
                if self._hash_record(record) != record.record_hash:
                    return False
                previous = record.record_hash
            return True

    @staticmethod
    def _hash_record(record: AuditRecord) -> str:
        payload = {
            "domain": record.domain.value,
            "status": record.status,
            "run_id": record.run_id,
            "commit_sha": record.commit_sha,
            "source": record.source,
            "version": record.version,
            "timestamp_utc": record.timestamp_utc.astimezone(timezone.utc).isoformat(),
            "metrics": record.metrics,
            "violations": list(record.violations),
            "artifact_uri": record.artifact_uri,
            "previous_hash": record.previous_hash,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return sha256(canonical.encode("utf-8")).hexdigest()
