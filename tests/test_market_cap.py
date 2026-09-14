import pandas as pd
import pytest

from mercado_financeiro.pit.market_cap import (
    classify_share_class,
    compute_market_cap_asof,
    resolve_security_issuer_asof,
)


def _shares() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "issuer_id": "00.000.001/0001-00",
                "reference_date": "2025-12-31",
                "available_from": "2026-03-20",
                "filing_version": 1,
                "ordinary_issued": 3,
                "preferred_issued": 5,
                "total_issued": 8,
                "ordinary_treasury": 0,
                "preferred_treasury": 0,
                "total_treasury": 0,
                "ordinary_outstanding": 3,
                "preferred_outstanding": 5,
                "total_outstanding": 8,
                "source": "CVM_DFP_COMPOSICAO_CAPITAL",
                "vintage_mode": "conservative_latest_snapshot",
            }
        ]
    )


def _security_history() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "security_id": "ISIN:ON",
                "ticker": "TEST3",
                "cfi_code": "ESXXXX",
                "valid_from": "2024-01-01",
                "valid_to_exclusive": pd.NaT,
            },
            {
                "security_id": "ISIN:PN",
                "ticker": "TEST4",
                "cfi_code": "EPXXXX",
                "valid_from": "2024-01-01",
                "valid_to_exclusive": pd.NaT,
            },
        ]
    )


def _issuer_map() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "TEST3",
                "issuer_id": "00.000.001/0001-00",
                "valid_from": "2024-01-01",
                "valid_to_exclusive": pd.NaT,
                "available_from": "2024-01-01",
            },
            {
                "ticker": "TEST4",
                "issuer_id": "00.000.001/0001-00",
                "valid_from": "2024-01-01",
                "valid_to_exclusive": pd.NaT,
                "available_from": "2024-01-01",
            },
        ]
    )


def test_classify_share_class_fails_closed_for_other_structures():
    assert classify_share_class("ESXXXX") == "ordinary"
    assert classify_share_class("EPXXXX") == "preferred"
    assert classify_share_class("CIVXXX") == "unsupported"
    assert classify_share_class(None) == "unsupported"


def test_resolve_security_issuer_blocks_future_mapping():
    mapping = _issuer_map()
    mapping.loc[mapping["ticker"] == "TEST4", "available_from"] = "2026-05-01"

    bridge = resolve_security_issuer_asof(_security_history(), mapping, "2026-04-01")
    on = bridge.loc[bridge["ticker"] == "TEST3"].iloc[0]
    pn = bridge.loc[bridge["ticker"] == "TEST4"].iloc[0]

    assert on["issuer_resolution_status"] == "resolved"
    assert pn["issuer_resolution_status"] == "unresolved_issuer"


def test_resolve_security_issuer_rejects_ambiguous_active_ticker():
    mapping = pd.concat(
        [
            _issuer_map(),
            pd.DataFrame(
                [
                    {
                        "ticker": "TEST3",
                        "issuer_id": "99.999.999/0001-99",
                        "valid_from": "2024-01-01",
                        "valid_to_exclusive": pd.NaT,
                        "available_from": "2024-01-01",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )

    with pytest.raises(ValueError, match="ambiguous active ticker-to-issuer mappings"):
        resolve_security_issuer_asof(_security_history(), mapping, "2026-04-01")


def test_market_cap_resolves_single_on_and_single_pn():
    asof = "2026-04-01"
    bridge = resolve_security_issuer_asof(_security_history(), _issuer_map(), asof)
    prices = pd.DataFrame(
        [
            {"security_id": "ISIN:ON", "price_date": asof, "close_price": 10.0},
            {"security_id": "ISIN:PN", "price_date": asof, "close_price": 20.0},
        ]
    )

    result = compute_market_cap_asof(prices, _shares(), bridge, asof)

    caps = dict(zip(result.security_caps["security_id"], result.security_caps["security_market_cap"]))
    assert caps == {"ISIN:ON": 30.0, "ISIN:PN": 100.0}
    issuer = result.issuer_caps.iloc[0]
    assert issuer["issuer_market_cap"] == 130.0
    assert issuer["market_cap_status"] == "resolved"


def test_market_cap_blocks_aggregate_preferred_shares_when_multiple_pref_securities_exist():
    asof = "2026-04-01"
    securities = pd.concat(
        [
            _security_history(),
            pd.DataFrame(
                [
                    {
                        "security_id": "ISIN:PNA",
                        "ticker": "TEST5",
                        "cfi_code": "EPXXXX",
                        "valid_from": "2024-01-01",
                        "valid_to_exclusive": pd.NaT,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    mappings = pd.concat(
        [
            _issuer_map(),
            pd.DataFrame(
                [
                    {
                        "ticker": "TEST5",
                        "issuer_id": "00.000.001/0001-00",
                        "valid_from": "2024-01-01",
                        "valid_to_exclusive": pd.NaT,
                        "available_from": "2024-01-01",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    bridge = resolve_security_issuer_asof(securities, mappings, asof)
    preferred = bridge.loc[bridge["share_class"] == "preferred"]
    assert set(preferred["class_resolution_status"]) == {"ambiguous_multiple_securities"}

    prices = pd.DataFrame(
        [
            {"security_id": "ISIN:ON", "price_date": asof, "close_price": 10.0},
            {"security_id": "ISIN:PN", "price_date": asof, "close_price": 20.0},
            {"security_id": "ISIN:PNA", "price_date": asof, "close_price": 30.0},
        ]
    )
    result = compute_market_cap_asof(prices, _shares(), bridge, asof)
    issuer = result.issuer_caps.iloc[0]
    assert pd.isna(issuer["issuer_market_cap"])
    assert "preferred_class_unresolved" in issuer["market_cap_status"]


def test_market_cap_blocks_shares_before_filing_availability():
    asof = "2026-02-01"
    bridge = resolve_security_issuer_asof(_security_history(), _issuer_map(), asof)
    prices = pd.DataFrame(
        [
            {"security_id": "ISIN:ON", "price_date": asof, "close_price": 10.0},
            {"security_id": "ISIN:PN", "price_date": asof, "close_price": 20.0},
        ]
    )

    result = compute_market_cap_asof(prices, _shares(), bridge, asof)
    assert result.security_caps.empty
    assert result.issuer_caps.empty
