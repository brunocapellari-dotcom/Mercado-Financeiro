from datetime import datetime, timezone
import pandas as pd
import pytest
from mercado_financeiro.cloud import (
    AsOfQuerySpec, DataSLA, canonical_cloud_datasets, canonical_cloud_tables,
    compare_snapshots, compile_latest_asof_sql, evaluate_data_sla,
    latest_known_asof, raw_object_key,
)
from mercado_financeiro.security import build_source_manifest

def test_cloud_layout_matches_final_data_flow():
    assert [x.dataset_id for x in canonical_cloud_datasets()] == [
        "mf_raw",
        "mf_normalized",
        "mf_canonical",
        "mf_derived",
        "mf_analytics",
        "mf_research",
    ]
    tables = {x.table_id: x for x in canonical_cloud_tables()}
    assert tables["fundamentals"].pit_required
    assert tables["source_manifest"].append_only
    assert tables["market_quotes"].layer.value == "canonical"
    assert tables["feature_mart"].layer.value == "derived"
    assert tables["paper_run"].layer.value == "analytics"

def test_raw_object_key_is_content_addressed():
    manifest = build_source_manifest(b"abc", source_name="B3 COTAHIST", source_url="https://www.b3.com.br/test", retrieved_at=datetime(2026,9,29,12,tzinfo=timezone.utc))
    key = raw_object_key(manifest)
    assert manifest.sha256 in key and key.startswith("raw/b3-cotahist/2026/09/29/")

def test_asof_filters_before_latest_selection():
    frame = pd.DataFrame({"security_id":["A","A","A"],"available_from":["2026-01-01T00:00:00Z","2026-02-01T00:00:00Z","2026-03-01T00:00:00Z"],"filing_version":[1,2,3],"value":[10,20,999]})
    result = latest_known_asof(frame,"2026-02-15T00:00:00Z",partition_by=("security_id",),tie_breakers=("filing_version",))
    assert result.iloc[0]["value"] == 20
    spec=AsOfQuerySpec("fundamentals",("security_id",),tie_breakers=("filing_version",))
    assert "WHERE `available_from` <= @cutoff QUALIFY" in compile_latest_asof_sql(spec,dialect="bigquery")
    assert 'WHERE "available_from" <= ? QUALIFY' in compile_latest_asof_sql(spec,dialect="duckdb")

def test_snapshot_diff_and_sla_fail_closed():
    previous=pd.DataFrame({"id":["a","b","c","d"],"value":[1,2,3,4]})
    current=pd.DataFrame({"id":["a","b"],"value":[1,9],"new":[1,1]})
    diff=compare_snapshots(previous,current,keys=("id",))
    result=evaluate_data_sla(observed_at="2026-09-29T11:00:00Z",now="2026-09-29T12:00:00Z",current_rows=2,previous_rows=4,diff=diff,sla=DataSLA(max_age=pd.Timedelta(hours=2),max_row_drop_fraction=0.25))
    assert not result.approved
    assert {"row_count_drop","schema_drift"}.issubset(result.reasons)


def test_asof_sql_rejects_untrusted_identifiers():
    with pytest.raises(ValueError, match="unsafe identifier"):
        AsOfQuerySpec("fundamentals;DROP_TABLE", ("security_id",))
    with pytest.raises(ValueError, match="unsafe identifier"):
        AsOfQuerySpec(
            "fundamentals",
            ("security_id",),
            available_from="available_from) OR 1=1",
        )
