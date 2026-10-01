# Mercado Financeiro — GitHub Research Integration 2026-10-01

Status: APPROVED RESEARCH/ARCHITECTURE ADDENDUM

LIVE remains blocked by the existing statistical/data/risk gates.

## Quant Research Factory

Adapt Microsoft RD-Agent methodology for iterative quantitative R&D:

`hypothesis -> factor/model proposal -> implementation -> experiment -> backtest -> critique -> mutation -> out-of-sample -> audit`.

The system must not auto-promote a strategy from a successful backtest.

Required independent roles:

- Hypothesis/Research;
- Data/Identity;
- Feature/Factor;
- Model/Experiment;
- Statistical Auditor;
- Overfitting Auditor;
- Risk Auditor.

Qlib remains an approved research reference/component where already selected.

## Feature/Data Graph

POC:

- Apache Hamilton — feature dependency DAG.
- Ibis — backend-portable dataframe expression layer.
- Marimo — Git-friendly reproducible research workbench.

The same feature definition should be reproducible locally and in the production analytical backend where feasible.

## Portfolio Risk Lab

Benchmark rather than stack libraries blindly:

- skfolio — current candidate.
- Riskfolio-Lib — compare CVaR/CDaR, HRP/HERC/NCO, Black-Litterman, risk budgeting and related methods.
- QuantInvestStrats/qis — reference/benchmark for performance attribution, ex-ante/ex-post risk, tracking error, Euler contribution and reproducible factsheets.

Only methods that improve validated coverage or correctness are promoted.

## Terminal / research UX

Fincept Terminal is REFERENCE only for financial terminal, multi-source research, portfolio/workflow and quant-lab UX. Its AGPL/open-vs-enterprise licensing means no unreviewed code incorporation.

OpenBB remains the preferred open financial-data platform/reference where already approved.

## Experiment governance

Every experiment records:

- dataset/vintage/cutoff;
- universe definition;
- code/feature/model versions;
- costs/slippage/liquidity assumptions;
- train/validation/test windows;
- random seeds where relevant;
- metrics including calibration/stability;
- PBO/Deflated Sharpe or equivalent anti-overfitting evidence where applicable.

Research automation increases experiment throughput; it never weakens the Risk Gate.
