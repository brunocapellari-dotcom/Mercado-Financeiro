from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from mercado_financeiro.execution import ObservedB3SettlementCalendar


def _calendar() -> ObservedB3SettlementCalendar:
    # 2026-04-21 (Tiradentes) deliberately absent from observed sessions.
    sessions = pd.to_datetime(
        ["2026-04-17", "2026-04-20", "2026-04-22", "2026-04-23", "2026-04-24"]
    )
    return ObservedB3SettlementCalendar.from_observed_sessions(
        sessions,
        source_bytes=b"official-b3-session-evidence",
        source_name="B3_COTAHIST",
    )


def test_observed_b3_calendar_skips_non_session_holiday_for_settlement():
    calendar = _calendar()
    trade = datetime(2026, 4, 20, 16, 30, tzinfo=ZoneInfo("America/Sao_Paulo"))
    settlement = calendar.add_business_days(trade, 2)
    assert settlement.date().isoformat() == "2026-04-23"
    assert settlement.hour == 16
    assert calendar.verified
    assert calendar.audit.sessions == 5


def test_observed_b3_calendar_fails_closed_outside_verified_coverage():
    calendar = _calendar()
    trade = datetime(2026, 4, 24, 16, 30, tzinfo=ZoneInfo("America/Sao_Paulo"))
    with pytest.raises(RuntimeError, match="exceeds verified B3 session coverage"):
        calendar.add_business_days(trade, 1)


def test_observed_b3_calendar_rejects_unobserved_trade_date_and_weekend_sessions():
    calendar = _calendar()
    holiday = datetime(2026, 4, 21, 12, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
    with pytest.raises(RuntimeError, match="not an observed B3 session"):
        calendar.add_business_days(holiday, 1)

    with pytest.raises(ValueError, match="weekends"):
        ObservedB3SettlementCalendar.from_observed_sessions(
            pd.to_datetime(["2026-04-18", "2026-04-20"]),
            source_bytes=b"x",
            source_name="B3_COTAHIST",
        )


def test_observed_b3_calendar_requires_source_provenance():
    with pytest.raises(ValueError, match="source_bytes"):
        ObservedB3SettlementCalendar.from_observed_sessions(
            pd.to_datetime(["2026-04-17", "2026-04-20"]),
            source_bytes=b"",
            source_name="B3_COTAHIST",
        )
