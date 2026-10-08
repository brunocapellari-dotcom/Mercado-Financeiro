from __future__ import annotations

import unicodedata

import pandas as pd


_REQUIRED_DFP_COLUMNS = {
    "CNPJ_CIA",
    "DT_REFER",
    "VERSAO",
    "available_from",
    "QT_ACAO_ORDIN_CAP_INTEGR",
    "QT_ACAO_PREF_CAP_INTEGR",
    "QT_ACAO_TOTAL_CAP_INTEGR",
    "QT_ACAO_ORDIN_TESOURO",
    "QT_ACAO_PREF_TESOURO",
    "QT_ACAO_TOTAL_TESOURO",
}

_REQUIRED_FRE_CAPITAL_COLUMNS = {
    "CNPJ_Companhia",
    "Data_Referencia",
    "Versao",
    "ID_Documento",
    "available_from",
    "Tipo_Capital",
    "Quantidade_Acoes_Ordinarias",
    "Quantidade_Acoes_Preferenciais",
    "Quantidade_Total_Acoes",
}

_REQUIRED_FRE_TREASURY_COLUMNS = {
    "CNPJ_Companhia",
    "Data_Referencia",
    "Versao",
    "ID_Documento",
    "available_from",
    "Classe_Valor_Mobiliario",
    "Historico_Exercicio",
    "Quantidade_Acoes_Tesouraria",
}

_STANDARD_SHARE_COLUMNS = [
    "issuer_id",
    "reference_date",
    "available_from",
    "filing_version",
    "document_id",
    "ordinary_issued",
    "preferred_issued",
    "total_issued",
    "ordinary_treasury",
    "preferred_treasury",
    "total_treasury",
    "ordinary_outstanding",
    "preferred_outstanding",
    "total_outstanding",
    "eligible_for_valuation",
    "shares_status",
    "source_priority",
    "source",
    "vintage_mode",
    "capital_approval_date",
]


def _normalized_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).upper().strip()


def _numeric_nonnegative_integral(series: pd.Series, name: str) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    if values.isna().any():
        raise ValueError(f"{name} contains null/non-numeric values")
    if (values < 0).any():
        raise ValueError(f"{name} contains negative values")
    if ((values % 1) != 0).any():
        raise ValueError(f"{name} contains non-integral share counts")
    return values.astype("int64")


def _optional_class_count(series: pd.Series, name: str) -> pd.Series:
    raw = series.copy()
    text = raw.astype("string").str.strip()
    missing = raw.isna() | text.eq("")
    values = pd.to_numeric(raw.where(~missing), errors="coerce")
    invalid = ~missing & values.isna()
    if invalid.any():
        raise ValueError(f"{name} contains non-numeric values")
    if (values.dropna() < 0).any():
        raise ValueError(f"{name} contains negative values")
    fractional = values.dropna() % 1
    if (fractional != 0).any():
        raise ValueError(f"{name} contains non-integral share counts")
    return values


def _standardize_share_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for column in _STANDARD_SHARE_COLUMNS:
        if column not in out.columns:
            out[column] = pd.NA
    return out[_STANDARD_SHARE_COLUMNS].copy()


def normalize_dfp_shares_outstanding(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize audited DFP capital composition into PIT share counts.

    This function expects `available_from` to have already been derived from the
    filing version represented by the source row. It fails closed on arithmetic
    inconsistencies instead of repairing them silently.
    """
    missing = _REQUIRED_DFP_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")

    out = df.copy()
    out["reference_date"] = pd.to_datetime(out["DT_REFER"], errors="coerce")
    out["available_from"] = pd.to_datetime(out["available_from"], errors="coerce")
    if out[["reference_date", "available_from"]].isna().any().any():
        raise ValueError("reference_date/available_from contains null or invalid values")

    out["filing_version"] = pd.to_numeric(out["VERSAO"], errors="coerce")
    if out["filing_version"].isna().any():
        raise ValueError("VERSAO contains null/non-numeric values")
    out["filing_version"] = out["filing_version"].astype("int64")

    numeric_map = {
        "ordinary_issued": "QT_ACAO_ORDIN_CAP_INTEGR",
        "preferred_issued": "QT_ACAO_PREF_CAP_INTEGR",
        "total_issued": "QT_ACAO_TOTAL_CAP_INTEGR",
        "ordinary_treasury": "QT_ACAO_ORDIN_TESOURO",
        "preferred_treasury": "QT_ACAO_PREF_TESOURO",
        "total_treasury": "QT_ACAO_TOTAL_TESOURO",
    }
    for target, source in numeric_map.items():
        out[target] = _numeric_nonnegative_integral(out[source], source)

    issued_mismatch = out["total_issued"] != out["ordinary_issued"] + out["preferred_issued"]
    if issued_mismatch.any():
        raise ValueError(f"issued share totals mismatch on {int(issued_mismatch.sum())} rows")

    treasury_mismatch = out["total_treasury"] != (
        out["ordinary_treasury"] + out["preferred_treasury"]
    )
    if treasury_mismatch.any():
        raise ValueError(f"treasury share totals mismatch on {int(treasury_mismatch.sum())} rows")

    if (out["ordinary_treasury"] > out["ordinary_issued"]).any():
        raise ValueError("ordinary treasury shares exceed issued shares")
    if (out["preferred_treasury"] > out["preferred_issued"]).any():
        raise ValueError("preferred treasury shares exceed issued shares")

    out["ordinary_outstanding"] = out["ordinary_issued"] - out["ordinary_treasury"]
    out["preferred_outstanding"] = out["preferred_issued"] - out["preferred_treasury"]
    out["total_outstanding"] = out["ordinary_outstanding"] + out["preferred_outstanding"]
    out["issuer_id"] = out["CNPJ_CIA"].astype(str).str.strip()
    out["document_id"] = out.get("ID_DOC", pd.Series(pd.NA, index=out.index))
    out["eligible_for_valuation"] = True
    out["shares_status"] = "resolved_dfp_issued_and_treasury"
    out["source_priority"] = 200
    out["source"] = "CVM_DFP_COMPOSICAO_CAPITAL"
    out["vintage_mode"] = "conservative_latest_snapshot"
    out["capital_approval_date"] = pd.NaT
    return _standardize_share_columns(out)


def normalize_fre_issued_shares(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize historical FRE ``Capital Emitido`` share observations.

    ``Data_Autorizacao_Aprovacao`` is provenance only. It is never treated as the
    information-availability timestamp or as a verified economically-effective date.
    Until treasury stock is independently reconciled, FRE rows are retained as issued
    share observations but are *not* eligible for market-cap valuation.
    """
    missing = _REQUIRED_FRE_CAPITAL_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"missing FRE capital columns: {sorted(missing)}")

    out = df.copy()
    emitted = out["Tipo_Capital"].map(_normalized_text).eq("CAPITAL EMITIDO")
    out = out.loc[emitted].copy()
    if out.empty:
        return _standardize_share_columns(pd.DataFrame())

    out["reference_date"] = pd.to_datetime(out["Data_Referencia"], errors="coerce")
    out["available_from"] = pd.to_datetime(out["available_from"], errors="coerce")
    out["filing_version"] = pd.to_numeric(out["Versao"], errors="coerce")
    if out[["reference_date", "available_from", "filing_version"]].isna().any().any():
        raise ValueError("FRE capital contains invalid reference/availability/version")
    out["filing_version"] = out["filing_version"].astype("int64")
    out["document_id"] = out["ID_Documento"].astype(str).str.strip()
    if out["document_id"].eq("").any():
        raise ValueError("FRE capital contains empty ID_Documento")

    total = _numeric_nonnegative_integral(
        out["Quantidade_Total_Acoes"], "Quantidade_Total_Acoes"
    )
    ordinary = _optional_class_count(
        out["Quantidade_Acoes_Ordinarias"], "Quantidade_Acoes_Ordinarias"
    )
    preferred = _optional_class_count(
        out["Quantidade_Acoes_Preferenciais"], "Quantidade_Acoes_Preferenciais"
    )

    both_missing = ordinary.isna() & preferred.isna()
    if both_missing.any():
        raise ValueError("FRE capital has total shares but both class counts are missing")

    ordinary_missing = ordinary.isna() & preferred.notna()
    preferred_missing = preferred.isna() & ordinary.notna()
    ordinary.loc[ordinary_missing] = total.loc[ordinary_missing] - preferred.loc[ordinary_missing]
    preferred.loc[preferred_missing] = total.loc[preferred_missing] - ordinary.loc[preferred_missing]
    if (ordinary.dropna() < 0).any() or (preferred.dropna() < 0).any():
        raise ValueError("FRE class count inferred from total is negative")

    ordinary = ordinary.astype("int64")
    preferred = preferred.astype("int64")
    mismatch = total != ordinary + preferred
    if mismatch.any():
        raise ValueError(f"FRE issued share totals mismatch on {int(mismatch.sum())} rows")

    out["ordinary_issued"] = ordinary
    out["preferred_issued"] = preferred
    out["total_issued"] = total
    out["issuer_id"] = out["CNPJ_Companhia"].astype(str).str.strip()
    if out["issuer_id"].eq("").any():
        raise ValueError("FRE capital contains empty issuer CNPJ")

    if "Data_Autorizacao_Aprovacao" in out.columns:
        approval_raw = out["Data_Autorizacao_Aprovacao"]
        approval = pd.to_datetime(approval_raw, errors="coerce")
        nonempty = approval_raw.notna() & approval_raw.astype("string").str.strip().ne("")
        if (nonempty & approval.isna()).any():
            raise ValueError("FRE capital contains invalid Data_Autorizacao_Aprovacao")
        out["capital_approval_date"] = approval
    else:
        out["capital_approval_date"] = pd.NaT

    keys = ["issuer_id", "reference_date", "filing_version", "document_id"]
    counts = ["ordinary_issued", "preferred_issued", "total_issued"]
    selected: list[pd.DataFrame] = []
    for _, group in out.groupby(keys, sort=False, dropna=False):
        distinct_counts = group[counts].drop_duplicates()
        if len(distinct_counts) > 1:
            if group["capital_approval_date"].isna().any():
                raise ValueError(
                    "conflicting FRE Capital Emitido rows require dated alteration evidence"
                )
            latest_approval = group["capital_approval_date"].max()
            group = group.loc[group["capital_approval_date"].eq(latest_approval)].copy()
        else:
            dated = group.loc[group["capital_approval_date"].notna()]
            if not dated.empty:
                latest_approval = dated["capital_approval_date"].max()
                group = group.loc[group["capital_approval_date"].eq(latest_approval)].copy()

        if len(group[counts].drop_duplicates()) > 1:
            raise ValueError(
                "conflicting FRE Capital Emitido rows at the same latest alteration date"
            )
        selected.append(group.tail(1))

    out = pd.concat(selected, ignore_index=True)
    out = out.sort_values(keys, kind="stable").reset_index(drop=True)

    for column in (
        "ordinary_treasury",
        "preferred_treasury",
        "total_treasury",
        "ordinary_outstanding",
        "preferred_outstanding",
        "total_outstanding",
    ):
        out[column] = pd.NA
    out["eligible_for_valuation"] = False
    out["shares_status"] = "issued_only_treasury_unresolved"
    out["source_priority"] = 100
    out["source"] = "CVM_FRE_CAPITAL_SOCIAL"
    out["vintage_mode"] = "filing_receipt_pit"
    return _standardize_share_columns(out)


def _treasury_class(value: object) -> str:
    text = _normalized_text(value)
    compact = text.replace(" ", "")
    if compact == "ON" or "ORDIN" in text:
        return "ordinary"
    if compact == "PN" or "PREFER" in text:
        return "preferred"
    if text in {"ACAO", "ACOES", "ACAO TOTAL", "ACOES TOTAL", "TOTAL DE ACOES"}:
        return "aggregate"
    return "unsupported"


def normalize_fre_treasury_shares(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize modern and legacy FRE end-of-exercise treasury observations.

    Modern vintages report an explicit end-of-exercise history field and one treasury
    balance by security class. Legacy vintages use the old Item 19.3 layout: the file
    itself is already the end-of-last-fiscal-year snapshot and can contain multiple
    acquisition lots. Those lots are summed by class. Unknown class evidence is
    preserved as unsupported so valuation fails closed downstream.
    """

    base_required = {
        "CNPJ_Companhia",
        "Data_Referencia",
        "Versao",
        "ID_Documento",
        "available_from",
    }
    missing_base = base_required - set(df.columns)
    if missing_base:
        raise ValueError(f"missing FRE treasury identity columns: {sorted(missing_base)}")

    modern_fields = {
        "Classe_Valor_Mobiliario",
        "Historico_Exercicio",
        "Quantidade_Acoes_Tesouraria",
    }
    legacy_fields = {"Quantidade_Valor_Mobiliario"}
    modern = modern_fields.issubset(df.columns)
    legacy = legacy_fields.issubset(df.columns)
    if not modern and not legacy:
        expected = sorted(modern_fields | legacy_fields)
        raise ValueError(
            f"unsupported FRE treasury schema; expected modern or legacy fields from {expected}; "
            f"observed={sorted(map(str, df.columns))}"
        )

    out = df.copy()
    out["reference_date"] = pd.to_datetime(out["Data_Referencia"], errors="coerce")
    out["available_from"] = pd.to_datetime(out["available_from"], errors="coerce")
    out["filing_version"] = pd.to_numeric(out["Versao"], errors="coerce")
    if out[["reference_date", "available_from", "filing_version"]].isna().any().any():
        raise ValueError("FRE treasury contains invalid reference/availability/version")
    out["filing_version"] = out["filing_version"].astype("int64")
    out["document_id"] = out["ID_Documento"].astype(str).str.strip()
    if out["document_id"].eq("").any():
        raise ValueError("FRE treasury contains empty ID_Documento")
    out["issuer_id"] = out["CNPJ_Companhia"].astype(str).str.strip()
    if out["issuer_id"].eq("").any():
        raise ValueError("FRE treasury contains empty issuer CNPJ")

    output_columns = [
        "issuer_id",
        "reference_date",
        "available_from",
        "filing_version",
        "document_id",
        "treasury_class",
        "treasury_count",
        "treasury_raw_count",
        "treasury_raw_class",
        "treasury_status",
    ]

    if modern:
        final_balance = out["Historico_Exercicio"].map(_normalized_text).eq("SALDO FINAL")
        out = out.loc[final_balance].copy()
        if out.empty:
            return pd.DataFrame(columns=output_columns)

        out["treasury_count"] = _numeric_nonnegative_integral(
            out["Quantidade_Acoes_Tesouraria"], "Quantidade_Acoes_Tesouraria"
        )
        out["treasury_raw_class"] = out["Classe_Valor_Mobiliario"].astype(str).str.strip()
        out["treasury_class"] = out["Classe_Valor_Mobiliario"].map(_treasury_class)
        out["treasury_raw_count"] = out["treasury_count"]
        out["treasury_status"] = "valid"

        keys = [
            "issuer_id",
            "reference_date",
            "filing_version",
            "document_id",
            "treasury_raw_class",
        ]
        duplicate = out.duplicated(keys, keep=False)
        if duplicate.any():
            grouped = out.loc[duplicate].groupby(keys, dropna=False)["treasury_count"].nunique()
            if grouped.gt(1).any():
                raise ValueError("conflicting FRE treasury rows within the same filing/class")
            out = out.drop_duplicates(keys, keep="last")
        return out[output_columns].reset_index(drop=True)

    legacy_counts = pd.to_numeric(out["Quantidade_Valor_Mobiliario"], errors="coerce")
    if legacy_counts.isna().any():
        raise ValueError("Quantidade_Valor_Mobiliario contains null/non-numeric values")
    if ((legacy_counts % 1) != 0).any():
        raise ValueError("Quantidade_Valor_Mobiliario contains non-integral share counts")
    out["treasury_raw_count"] = legacy_counts.astype("int64")
    negative = legacy_counts < 0
    out["treasury_status"] = "valid"
    out.loc[negative, "treasury_status"] = "invalid_negative_quantity"
    out["treasury_count"] = legacy_counts.where(~negative).astype("Int64")

    legacy_class_fields = (
        "Especie_Acao",
        "Descricao_Valor_Mobiliario",
        "Valor_Mobiliario",
        "Tipo_Classe_Acao_Preferencial",
    )

    def legacy_class_evidence(row: pd.Series) -> tuple[str, str]:
        values: list[str] = []
        classified = "unsupported"
        preferred_detail = ""
        for column in legacy_class_fields:
            if column not in row.index:
                continue
            raw = "" if pd.isna(row[column]) else str(row[column]).strip()
            if not raw:
                continue
            values.append(f"{column}={raw}")
            candidate = _treasury_class(raw)
            if candidate != "unsupported" and classified == "unsupported":
                classified = candidate
            if column == "Tipo_Classe_Acao_Preferencial":
                preferred_detail = _normalized_text(raw)

        if classified == "unsupported" and preferred_detail not in {
            "",
            "NA",
            "N/A",
            "NAO APLICAVEL",
            "NAO SE APLICA",
        }:
            classified = "preferred"

        raw_evidence = " | ".join(values) if values else "UNSPECIFIED"
        return classified, raw_evidence

    classified = out.apply(legacy_class_evidence, axis=1)
    out["treasury_class"] = [item[0] for item in classified]
    out["treasury_raw_class"] = [item[1] for item in classified]

    group_keys = [
        "issuer_id",
        "reference_date",
        "filing_version",
        "document_id",
        "treasury_class",
        "treasury_raw_class",
    ]
    valid = out.loc[out["treasury_status"].eq("valid")].copy()
    invalid = out.loc[~out["treasury_status"].eq("valid")].copy()

    grouped_frames: list[pd.DataFrame] = []
    if not valid.empty:
        grouped_frames.append(
            valid.groupby(group_keys + ["treasury_status"], as_index=False, dropna=False)
            .agg(
                available_from=("available_from", "max"),
                treasury_count=("treasury_count", "sum"),
                treasury_raw_count=("treasury_raw_count", "sum"),
            )
            .reset_index(drop=True)
        )
    if not invalid.empty:
        invalid_grouped = (
            invalid.groupby(
                group_keys + ["treasury_status"],
                as_index=False,
                dropna=False,
            )
            .agg(
                available_from=("available_from", "max"),
                treasury_raw_count=("treasury_raw_count", "sum"),
            )
            .reset_index(drop=True)
        )
        invalid_grouped["treasury_count"] = pd.NA
        grouped_frames.append(invalid_grouped)

    if not grouped_frames:
        return pd.DataFrame(columns=output_columns)
    out = pd.concat(grouped_frames, ignore_index=True, sort=False)
    return out[output_columns].reset_index(drop=True)


def reconcile_fre_issued_and_treasury(
    issued: pd.DataFrame,
    treasury: pd.DataFrame,
) -> pd.DataFrame:
    """Produce valuation-eligible FRE outstanding shares when treasury is provable.

    The resolver fails closed when an aggregate treasury balance cannot be allocated
    between non-zero ordinary and preferred issued capital. It never assumes a missing
    treasury class is zero when both share classes exist.
    """
    issued_required = {
        "issuer_id",
        "reference_date",
        "available_from",
        "filing_version",
        "document_id",
        "ordinary_issued",
        "preferred_issued",
        "total_issued",
    }
    treasury_required = {
        "issuer_id",
        "reference_date",
        "available_from",
        "filing_version",
        "document_id",
        "treasury_class",
        "treasury_count",
    }
    missing_issued = issued_required - set(issued.columns)
    missing_treasury = treasury_required - set(treasury.columns)
    if missing_issued:
        raise ValueError(f"issued history missing fields: {sorted(missing_issued)}")
    if missing_treasury:
        raise ValueError(f"treasury history missing fields: {sorted(missing_treasury)}")

    out = _standardize_share_columns(issued)
    if out.empty:
        return out

    treasury_frame = treasury.copy()
    for column in ("reference_date", "available_from"):
        treasury_frame[column] = pd.to_datetime(treasury_frame[column], errors="coerce")
    if treasury_frame[["reference_date", "available_from"]].isna().any().any():
        raise ValueError("treasury history contains invalid dates")

    key_columns = ["issuer_id", "reference_date", "filing_version", "document_id"]

    for index, row in out.iterrows():
        mask = pd.Series(True, index=treasury_frame.index)
        for key in key_columns:
            mask &= treasury_frame[key].eq(row[key])
        evidence = treasury_frame.loc[mask].copy()
        if evidence.empty:
            out.at[index, "shares_status"] = "issued_only_treasury_unavailable"
            continue

        out.at[index, "available_from"] = max(
            pd.Timestamp(row["available_from"]),
            pd.Timestamp(evidence["available_from"].max()),
        )
        if "treasury_status" in evidence.columns:
            invalid_status = (
                evidence["treasury_status"].fillna("invalid_unknown").astype(str).ne("valid")
            )
            if invalid_status.any():
                out.at[index, "shares_status"] = "invalid_treasury_source"
                continue
        if evidence["treasury_count"].isna().any():
            out.at[index, "shares_status"] = "invalid_treasury_source"
            continue
        if (
            evidence.loc[evidence["treasury_class"].eq("unsupported"), "treasury_count"]
            .gt(0)
            .any()
        ):
            out.at[index, "shares_status"] = "unsupported_treasury_class"
            continue

        ordinary_rows = evidence.loc[evidence["treasury_class"].eq("ordinary")]
        preferred_rows = evidence.loc[evidence["treasury_class"].eq("preferred")]
        aggregate_rows = evidence.loc[evidence["treasury_class"].eq("aggregate")]

        ordinary_present = not ordinary_rows.empty
        preferred_present = not preferred_rows.empty
        aggregate_present = not aggregate_rows.empty
        ordinary_treasury = int(ordinary_rows["treasury_count"].sum()) if ordinary_present else None
        preferred_treasury = int(preferred_rows["treasury_count"].sum()) if preferred_present else None
        aggregate_treasury = int(aggregate_rows["treasury_count"].sum()) if aggregate_present else None

        ordinary_issued = int(row["ordinary_issued"])
        preferred_issued = int(row["preferred_issued"])

        if aggregate_present:
            assert aggregate_treasury is not None
            if ordinary_present and preferred_present:
                assert ordinary_treasury is not None and preferred_treasury is not None
                if aggregate_treasury != ordinary_treasury + preferred_treasury:
                    out.at[index, "shares_status"] = "treasury_aggregate_inconsistent"
                    continue
            elif ordinary_present:
                assert ordinary_treasury is not None
                preferred_treasury = aggregate_treasury - ordinary_treasury
                if preferred_treasury < 0:
                    out.at[index, "shares_status"] = "treasury_aggregate_inconsistent"
                    continue
            elif preferred_present:
                assert preferred_treasury is not None
                ordinary_treasury = aggregate_treasury - preferred_treasury
                if ordinary_treasury < 0:
                    out.at[index, "shares_status"] = "treasury_aggregate_inconsistent"
                    continue
            elif aggregate_treasury == 0:
                ordinary_treasury = 0
                preferred_treasury = 0
            elif ordinary_issued == 0:
                ordinary_treasury = 0
                preferred_treasury = aggregate_treasury
            elif preferred_issued == 0:
                ordinary_treasury = aggregate_treasury
                preferred_treasury = 0
            else:
                out.at[index, "shares_status"] = "ambiguous_aggregate_treasury"
                continue
        else:
            if ordinary_issued == 0 and ordinary_treasury is None:
                ordinary_treasury = 0
            if preferred_issued == 0 and preferred_treasury is None:
                preferred_treasury = 0
            if ordinary_treasury is None or preferred_treasury is None:
                out.at[index, "shares_status"] = "treasury_class_incomplete"
                continue

        assert ordinary_treasury is not None and preferred_treasury is not None
        if ordinary_treasury > ordinary_issued or preferred_treasury > preferred_issued:
            out.at[index, "shares_status"] = "treasury_exceeds_issued"
            continue

        total_treasury = ordinary_treasury + preferred_treasury
        out.at[index, "ordinary_treasury"] = ordinary_treasury
        out.at[index, "preferred_treasury"] = preferred_treasury
        out.at[index, "total_treasury"] = total_treasury
        out.at[index, "ordinary_outstanding"] = ordinary_issued - ordinary_treasury
        out.at[index, "preferred_outstanding"] = preferred_issued - preferred_treasury
        out.at[index, "total_outstanding"] = int(row["total_issued"]) - total_treasury
        out.at[index, "eligible_for_valuation"] = True
        out.at[index, "shares_status"] = "resolved_fre_issued_and_treasury"
        out.at[index, "source"] = "CVM_FRE_CAPITAL_SOCIAL+TESOURARIA"
        out.at[index, "vintage_mode"] = "filing_receipt_pit"

    out["eligible_for_valuation"] = out["eligible_for_valuation"].fillna(False).astype(bool)
    return _standardize_share_columns(out)


def combine_share_histories(*frames: pd.DataFrame) -> pd.DataFrame:
    """Combine DFP/FRE PIT share histories under one deterministic source contract."""
    nonempty = [
        _standardize_share_columns(frame)
        for frame in frames
        if frame is not None and not frame.empty
    ]
    if not nonempty:
        return _standardize_share_columns(pd.DataFrame())
    out = pd.concat(nonempty, ignore_index=True)
    out["reference_date"] = pd.to_datetime(out["reference_date"], errors="coerce")
    out["available_from"] = pd.to_datetime(out["available_from"], errors="coerce")
    out["filing_version"] = pd.to_numeric(out["filing_version"], errors="coerce")
    out["source_priority"] = pd.to_numeric(out["source_priority"], errors="coerce").fillna(0)
    if out[["reference_date", "available_from", "filing_version"]].isna().any().any():
        raise ValueError("combined share history contains invalid dates/version")
    return out.sort_values(
        [
            "issuer_id",
            "reference_date",
            "available_from",
            "filing_version",
            "source_priority",
        ],
        kind="stable",
    ).reset_index(drop=True)


def shares_outstanding_asof(df: pd.DataFrame, asof: str | pd.Timestamp) -> pd.DataFrame:
    """Select the latest valuation-eligible share count per issuer at `asof`."""
    required = {"issuer_id", "reference_date", "available_from", "filing_version"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")

    ts = pd.Timestamp(asof)
    out = df.copy()
    out["reference_date"] = pd.to_datetime(out["reference_date"], errors="coerce")
    out["available_from"] = pd.to_datetime(out["available_from"], errors="coerce")
    if out[["reference_date", "available_from"]].isna().any().any():
        raise ValueError("reference_date/available_from contains null or invalid values")

    eligible = out.loc[(out["available_from"] <= ts) & (out["reference_date"] <= ts)].copy()
    if "eligible_for_valuation" in eligible.columns:
        flag = eligible["eligible_for_valuation"].fillna(False).astype(bool)
        eligible = eligible.loc[flag].copy()
    if eligible.empty:
        return eligible

    if "source_priority" not in eligible.columns:
        eligible["source_priority"] = 0
    eligible["source_priority"] = pd.to_numeric(
        eligible["source_priority"], errors="coerce"
    ).fillna(0)
    eligible = eligible.sort_values(
        [
            "issuer_id",
            "reference_date",
            "available_from",
            "filing_version",
            "source_priority",
        ],
        kind="stable",
    )
    return eligible.groupby("issuer_id", as_index=False, sort=False).tail(1).reset_index(drop=True)
