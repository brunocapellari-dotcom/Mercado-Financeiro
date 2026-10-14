# Point-in-Time Data Policy

## Objective

Prevent look-ahead, revision leakage and survivorship bias from entering research, validation or portfolio construction.

## Availability rule

A value is eligible only when its represented source version was actually available to the market/research system.

For CVM filings:

`eligible(asof) = available_from <= asof`

`DT_REFER`, fiscal year or accounting period never substitutes for publication/receipt time.

## CVM conservative track

Current annual structured FRE/DFP section files can materialize only the latest represented version while the filing ledger preserves multiple submissions. Therefore:

1. map section rows to the represented filing version;
2. derive `available_from` from `DT_RECEB`;
3. block the row before `available_from`;
4. never silently backfill a revised value into an earlier date;
5. persist snapshot fingerprint and collection timestamp;
6. label the lineage `conservative_latest_snapshot` until exact historical vintages are reconstructed.

The conservative track may sacrifice recency/coverage. It may not sacrifice causality.

## Security Master

Ticker is not an identity. The canonical entity layer must retain stable issuer/security identifiers and temporal validity for ticker, ISIN, class, listing, delisting and reorganizations. Overlapping SCD2 intervals are a hard failure.

## Market capitalization

Market cap must use point-in-time shares outstanding by class and a compatible market price on the same information set. Future capital structure revisions are prohibited.

## B3 COTAHIST daily bars

COTAHIST files are final end-of-day records collected after the fact. For replay:

1. `reference_date` = session close (18:00 America/Sao_Paulo) of `trade_date`;
2. `available_from` = next calendar day 08:00 America/Sao_Paulo — an *inferred*, conservative
   publication time (`availability_rule = inferido:trade_date+1d_08:00_local`), before the next open;
3. rows whose `available_from` is later than the file retrieval time are rejected;
4. paper/shadow decisions use `asof(bars, cutoff)` and execute strictly after the cutoff at the
   next session's opening price; the execution bar is never a decision input;
5. bars are unadjusted for corporate actions; implausible daily moves exclude the candidate and are
   reported, never silently repaired.

Implementation: `mercado_financeiro.operations.historical_replay`, runner
`scripts/run_historical_paper_replay.py` (raw files only in an external `MF_DATA_DIR`).

## Universe construction

The investable universe is reconstructed for each historical date and must retain securities that later delisted, merged, failed or became illiquid. Residual unmapped observations require explicit classification; silent dropping is prohibited.

## Derived data

Every materialized dataset/feature should carry, directly or through its manifest:

- reference date;
- available/publication date;
- collection date;
- source snapshot fingerprint;
- code/model version;
- upstream dependencies;
- vintage mode;
- quality/gate status.

## Promotion

No Tournament result can be promoted when a critical PIT, identity, corporate-action or universe gate is unresolved. LIVE capital remains independently blocked by statistical, execution and risk gates.
