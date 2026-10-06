"""
EPR reporting pipeline.

This module contains all the "Part 2" logic for the EPR case study:
 - clean & standardize product data (units, categories, jurisdictions, dedup)
 - join to the fee rate table and compute liability per jurisdiction/category
 - flag records that can't be confidently processed, with a reason code
 - build an audit trail so every output row can be traced back to its
   source record(s) and the transformations applied to it

Everything here is pure pandas (no Streamlit calls) so it can be unit
tested / reused independent of the UI.
"""

from __future__ import annotations

import difflib
from datetime import datetime

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Reference data / mapping tables
# ---------------------------------------------------------------------------

# Keyword -> canonical material category. Matching is substring-based on a
# lowercased material_description. Order matters: first match wins.
CATEGORY_MAP = {
    "Plastic": ["plastic", "pet", "pvc", "polypropylene", "hdpe", "ldpe", "pp", "eps"],
    "Cardboard/Paper": ["cardboard", "paper", "kraft"],
    "Glass": ["glass"],
    "Aluminium": ["aluminium", "aluminum", "alu"],
    "Steel": ["steel", "tin"],
}

# Recognized unit spellings -> multiplier to convert into kg
UNIT_TO_KG = {
    "kg": 1.0,
    "kgs": 1.0,
    "kilogram": 1.0,
    "kilograms": 1.0,
    "g": 0.001,
    "gram": 0.001,
    "grams": 0.001,
    "gm": 0.001,
}

# Source system precedence used to break ties when two records for the same
# SKU share the same last_updated timestamp (higher = more trusted).
SOURCE_PRIORITY = {"ERP": 3, "Supplier": 2, "Manual": 1}

REQUIRED_PRODUCT_COLUMNS = [
    "source_system",
    "sku",
    "product_name",
    "material_description",
    "packaging_weight",
    "weight_unit",
    "jurisdiction",
    "recyclable_flag",
    "last_updated",
]

REQUIRED_FEE_COLUMNS = [
    "jurisdiction",
    "material_category",
    "fee_per_kg_local_currency",
]


def categorize_material(material_description) -> str:
    """Map a free-text material description to a canonical category."""
    text = str(material_description).strip().lower()
    if text in ("", "nan", "none", "unknown"):
        return "Unmapped"
    for category, keywords in CATEGORY_MAP.items():
        if any(kw in text for kw in keywords):
            return category
    return "Other"


def standardize_jurisdiction(raw_value, known_jurisdictions, cutoff=0.6):
    """
    Fuzzy-match a raw jurisdiction string to the closest known jurisdiction
    (from the fee rate table). Returns (matched_value, was_fuzzy_matched, score).

    Uses difflib (stdlib) rather than an external fuzzy-matching library so
    the app has no extra install dependency.
    """
    text = str(raw_value).strip()
    if text == "" or text.lower() == "nan":
        return None, False, 0.0

    # exact / case-insensitive match first
    for known in known_jurisdictions:
        if text.lower() == known.lower():
            return known, False, 1.0

    matches = difflib.get_close_matches(text, known_jurisdictions, n=1, cutoff=cutoff)
    if matches:
        score = difflib.SequenceMatcher(None, text.lower(), matches[0].lower()).ratio()
        return matches[0], True, round(score, 2)

    return None, False, 0.0


def _parse_date(value):
    try:
        return pd.to_datetime(value)
    except Exception:
        return pd.NaT


def run_pipeline(product_df: pd.DataFrame, fee_df: pd.DataFrame) -> dict:
    """
    Run the full clean -> dedupe -> categorize -> standardize -> join ->
    fee-calc -> exception-flagging -> audit-trail pipeline.

    Returns a dict with keys:
        clean         cleaned, fee-calculated dataframe (one row per accepted SKU)
        exceptions    dataframe of rows that could not be confidently processed
        audit_log     long-format audit trail (one row per transformation applied)
        summary       total EPR fee liability per jurisdiction x category
        stats         dict of pipeline run statistics for the UI
    """
    df = product_df.copy()
    df.columns = [c.strip() for c in df.columns]

    missing_cols = [c for c in REQUIRED_PRODUCT_COLUMNS if c not in df.columns]
    if missing_cols:
        raise ValueError(
            f"Uploaded product file is missing required column(s): {missing_cols}"
        )

    fee = fee_df.copy()
    fee.columns = [c.strip() for c in fee.columns]
    missing_fee_cols = [c for c in REQUIRED_FEE_COLUMNS if c not in fee.columns]
    if missing_fee_cols:
        raise ValueError(
            f"Uploaded fee rate file is missing required column(s): {missing_fee_cols}"
        )

    known_jurisdictions = sorted(fee["jurisdiction"].dropna().unique().tolist())

    # ------------------------------------------------------------------
    # 0. Lineage scaffolding — every raw row gets a stable source_row_id so
    #    we can always trace an output row back to exactly which upload
    #    row(s) it came from.
    # ------------------------------------------------------------------
    df = df.reset_index(drop=True)
    df["source_row_id"] = df.index.map(lambda i: f"row_{i}")
    df["_lineage"] = df["source_system"].astype(str) + ":" + df["source_row_id"]

    audit_rows = []  # long-format audit log entries

    def log(row_ids, sku, field, from_value, to_value, rule):
        audit_rows.append(
            {
                "source_row_id": row_ids,
                "sku": sku,
                "field": field,
                "from_value": from_value,
                "to_value": to_value,
                "rule_applied": rule,
            }
        )

    exceptions = []  # rows we cannot confidently process

    def flag_exception(row, reason_code, detail):
        exceptions.append(
            {
                "source_row_id": row["source_row_id"],
                "source_system": row["source_system"],
                "sku": row.get("sku", None),
                "reason_code": reason_code,
                "detail": detail,
                "raw_record": row.drop(labels=["_lineage"], errors="ignore").to_dict(),
            }
        )

    # ------------------------------------------------------------------
    # 1. Missing SKU — nothing downstream can key off this row at all.
    # ------------------------------------------------------------------
    missing_sku_mask = df["sku"].isna() | (df["sku"].astype(str).str.strip() == "")
    for _, row in df[missing_sku_mask].iterrows():
        flag_exception(row, "MISSING_SKU", "SKU is missing; record cannot be identified or deduplicated.")
    df = df[~missing_sku_mask].copy()

    # ------------------------------------------------------------------
    # 2. Standardize units -> packaging_weight_kg
    # ------------------------------------------------------------------
    def to_kg(row):
        unit_raw = str(row["weight_unit"]).strip().lower()
        weight = row["packaging_weight"]
        if pd.isna(weight):
            return np.nan, unit_raw, "missing_weight"
        if unit_raw not in UNIT_TO_KG:
            return np.nan, unit_raw, "unrecognized_unit"
        return weight * UNIT_TO_KG[unit_raw], unit_raw, "ok"

    kg_values, units_seen, unit_status = [], [], []
    for _, row in df.iterrows():
        kg, unit_raw, status = to_kg(row)
        kg_values.append(kg)
        units_seen.append(unit_raw)
        unit_status.append(status)
    df["packaging_weight_kg"] = kg_values
    df["_unit_status"] = unit_status

    for _, row in df.iterrows():
        if row["_unit_status"] == "ok" and str(row["weight_unit"]).strip().lower() != "kg":
            log(
                row["source_row_id"], row["sku"], "packaging_weight",
                f"{row['packaging_weight']} {row['weight_unit']}",
                f"{row['packaging_weight_kg']:.5f} kg",
                "unit_converted_to_kg",
            )

    # ------------------------------------------------------------------
    # 3. Standardize material category
    # ------------------------------------------------------------------
    df["category"] = df["material_description"].apply(categorize_material)
    for _, row in df.iterrows():
        log(
            row["source_row_id"], row["sku"], "category",
            row["material_description"], row["category"],
            "keyword_mapped_to_category",
        )

    # ------------------------------------------------------------------
    # 4. Standardize jurisdiction (fuzzy match against fee table's list)
    # ------------------------------------------------------------------
    jur_matched, jur_fuzzy, jur_score = [], [], []
    for _, row in df.iterrows():
        matched, was_fuzzy, score = standardize_jurisdiction(row["jurisdiction"], known_jurisdictions)
        jur_matched.append(matched)
        jur_fuzzy.append(was_fuzzy)
        jur_score.append(score)
    df["jurisdiction_std"] = jur_matched
    df["_jurisdiction_fuzzy"] = jur_fuzzy
    df["_jurisdiction_score"] = jur_score

    for _, row in df.iterrows():
        if row["_jurisdiction_fuzzy"]:
            log(
                row["source_row_id"], row["sku"], "jurisdiction",
                row["jurisdiction"], row["jurisdiction_std"],
                f"fuzzy_matched_to_known_jurisdiction(score={row['_jurisdiction_score']})",
            )

    # ------------------------------------------------------------------
    # 5. Deduplicate: same SKU can appear from multiple source systems.
    #    Precedence: most recent last_updated wins; ties broken by source
    #    system trust order ERP > Supplier > Manual. This is a documented
    #    assumption, not a discovered fact about the business.
    # ------------------------------------------------------------------
    df["_last_updated_parsed"] = df["last_updated"].apply(_parse_date)
    df["_source_priority"] = df["source_system"].map(SOURCE_PRIORITY).fillna(0)

    dedup_notes = {}
    kept_rows = []
    for sku, group in df.groupby("sku", sort=False):
        if len(group) > 1:
            group_sorted = group.sort_values(
                ["_last_updated_parsed", "_source_priority"], ascending=[False, False]
            )
            winner = group_sorted.iloc[0]
            losers = group_sorted.iloc[1:]
            dedup_notes[sku] = {
                "kept_row_id": winner["source_row_id"],
                "kept_source": winner["source_system"],
                "discarded_row_ids": losers["source_row_id"].tolist(),
                "discarded_sources": losers["source_system"].tolist(),
            }
            log(
                winner["source_row_id"], sku, "record_selection",
                f"{len(group)} records from {group['source_system'].tolist()}",
                f"kept {winner['source_system']} (row {winner['source_row_id']})",
                "dedup_most_recent_last_updated_then_source_priority(ERP>Supplier>Manual)",
            )
            kept_rows.append(winner)
        else:
            kept_rows.append(group.iloc[0])

    df = pd.DataFrame(kept_rows).reset_index(drop=True)

    # ------------------------------------------------------------------
    # 6. Flag remaining exceptions (weight / category / jurisdiction issues)
    #    on the deduplicated set, then drop them from the "clean" output.
    # ------------------------------------------------------------------
    def classify(row):
        reasons = []
        if row["_unit_status"] == "missing_weight":
            reasons.append(("MISSING_WEIGHT", "packaging_weight is missing."))
        elif row["_unit_status"] == "unrecognized_unit":
            reasons.append(("UNRECOGNIZED_UNIT", f"weight_unit '{row['weight_unit']}' is not recognized."))
        elif pd.notna(row["packaging_weight_kg"]) and row["packaging_weight_kg"] <= 0:
            reasons.append(("NON_POSITIVE_WEIGHT", f"packaging_weight_kg = {row['packaging_weight_kg']}."))

        if row["category"] == "Unmapped":
            reasons.append(("UNMAPPABLE_MATERIAL", "material_description is missing or unrecognized."))

        if pd.isna(row["jurisdiction_std"]):
            reasons.append(("UNMAPPABLE_JURISDICTION", f"jurisdiction '{row['jurisdiction']}' does not match any known jurisdiction."))

        return reasons

    clean_rows, exception_rows = [], []
    for _, row in df.iterrows():
        reasons = classify(row)
        if reasons:
            for code, detail in reasons:
                exceptions.append(
                    {
                        "source_row_id": row["source_row_id"],
                        "source_system": row["source_system"],
                        "sku": row["sku"],
                        "reason_code": code,
                        "detail": detail,
                        "raw_record": row.drop(
                            labels=[c for c in df.columns if c.startswith("_")], errors="ignore"
                        ).to_dict(),
                    }
                )
        else:
            clean_rows.append(row)

    clean_df = pd.DataFrame(clean_rows).reset_index(drop=True)
    exceptions_df = pd.DataFrame(exceptions)

    # ------------------------------------------------------------------
    # 7. Join to fee rate table & compute fee liability
    # ------------------------------------------------------------------
    fee_norm = fee.copy()
    fee_norm["_j_key"] = fee_norm["jurisdiction"].str.strip().str.lower()
    fee_norm["_c_key"] = fee_norm["material_category"].str.strip().str.lower()

    if not clean_df.empty:
        clean_df["_j_key"] = clean_df["jurisdiction_std"].str.strip().str.lower()
        clean_df["_c_key"] = clean_df["category"].str.strip().str.lower()

        merged = clean_df.merge(
            fee_norm[["_j_key", "_c_key", "fee_per_kg_local_currency", "currency", "effective_from"]]
            if "currency" in fee_norm.columns and "effective_from" in fee_norm.columns
            else fee_norm[["_j_key", "_c_key", "fee_per_kg_local_currency"]],
            on=["_j_key", "_c_key"],
            how="left",
        )

        no_rate_mask = merged["fee_per_kg_local_currency"].isna()
        for _, row in merged[no_rate_mask].iterrows():
            exceptions.append(
                {
                    "source_row_id": row["source_row_id"],
                    "source_system": row["source_system"],
                    "sku": row["sku"],
                    "reason_code": "NO_MATCHING_FEE_RATE",
                    "detail": f"No fee rate defined for jurisdiction='{row['jurisdiction_std']}', category='{row['category']}'.",
                    "raw_record": {},
                }
            )

        merged = merged[~no_rate_mask].copy()
        merged["total_fee"] = merged["packaging_weight_kg"] * merged["fee_per_kg_local_currency"]

        for _, row in merged.iterrows():
            log(
                row["source_row_id"], row["sku"], "total_fee",
                f"{row['packaging_weight_kg']:.5f} kg x rate", f"{row['total_fee']:.5f}",
                "fee = packaging_weight_kg * fee_per_kg_local_currency",
            )

        merged.drop(columns=["_j_key", "_c_key"], inplace=True, errors="ignore")
        clean_df = merged
        exceptions_df = pd.DataFrame(exceptions)
    else:
        clean_df["total_fee"] = []
        clean_df["fee_per_kg_local_currency"] = []
        if "currency" in fee_norm.columns:
            clean_df["currency"] = []

    # ------------------------------------------------------------------
    # 8. Summary — fee liability per jurisdiction x category
    # ------------------------------------------------------------------
    if not clean_df.empty:
        group_cols = ["jurisdiction_std", "category"]
        agg = {"total_fee": "sum", "packaging_weight_kg": "sum", "sku": "count"}
        summary = (
            clean_df.groupby(group_cols)
            .agg(agg)
            .rename(
                columns={
                    "total_fee": "total_fee_liability",
                    "packaging_weight_kg": "total_weight_kg",
                    "sku": "sku_count",
                }
            )
            .reset_index()
            .rename(columns={"jurisdiction_std": "jurisdiction"})
            .sort_values(["jurisdiction", "category"])
        )
    else:
        summary = pd.DataFrame(
            columns=["jurisdiction", "category", "total_fee_liability", "total_weight_kg", "sku_count"]
        )

    # ------------------------------------------------------------------
    # 9. Tidy up output columns for display
    # ------------------------------------------------------------------
    display_cols = [
        "source_row_id", "source_system", "sku", "product_name",
        "material_description", "category",
        "packaging_weight", "weight_unit", "packaging_weight_kg",
        "jurisdiction", "jurisdiction_std",
        "recyclable_flag", "last_updated",
        "fee_per_kg_local_currency", "total_fee",
    ]
    if "currency" in clean_df.columns:
        display_cols.insert(display_cols.index("total_fee") + 1, "currency")
    display_cols = [c for c in display_cols if c in clean_df.columns]
    clean_display = clean_df[display_cols] if not clean_df.empty else pd.DataFrame(columns=display_cols)

    audit_log_df = pd.DataFrame(audit_rows)

    stats = {
        "raw_rows": int(len(product_df)),
        "clean_rows": int(len(clean_display)),
        "exception_rows": int(len(exceptions_df)),
        "duplicate_skus_resolved": len(dedup_notes),
        "total_liability_by_currency": (
            clean_df.groupby("currency")["total_fee"].sum().to_dict()
            if "currency" in clean_df.columns and not clean_df.empty
            else {}
        ),
    }

    return {
        "clean": clean_display,
        "exceptions": exceptions_df,
        "audit_log": audit_log_df,
        "summary": summary,
        "stats": stats,
        "dedup_notes": dedup_notes,
    }
