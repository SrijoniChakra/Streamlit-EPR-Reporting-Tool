import pandas as pd
import streamlit as st

st.set_page_config(page_title="Data Quality Assessment", page_icon="📋", layout="wide")
st.title("📋 Part 1 — Data Quality Assessment")

product_df = st.session_state.get("product_df")

if product_df is None:
    st.warning("No product file uploaded yet. Go to the **Home** page to upload one.")
    st.stop()

st.subheader("Auto-detected issues in your uploaded file")

n_rows = len(product_df)
issues = []

# Missing values
missing_counts = product_df.isna().sum()
for col, count in missing_counts.items():
    if count > 0:
        issues.append(("Missing values", col, f"{count} of {n_rows} rows missing"))

# Duplicate SKUs
if "sku" in product_df.columns:
    dup_skus = product_df["sku"].value_counts()
    dup_skus = dup_skus[dup_skus > 1]
    if len(dup_skus) > 0:
        issues.append(("Duplicate records", "sku", f"{len(dup_skus)} SKUs appear more than once (multiple source systems)"))

# Unit inconsistencies
if "weight_unit" in product_df.columns:
    units = product_df["weight_unit"].dropna().astype(str).str.strip().str.lower().unique().tolist()
    if len(units) > 1:
        issues.append(("Unit inconsistency", "weight_unit", f"Mixed units found: {units}"))

# Non-positive weights
if "packaging_weight" in product_df.columns:
    bad_weights = product_df[pd.to_numeric(product_df["packaging_weight"], errors="coerce") <= 0]
    if len(bad_weights) > 0:
        issues.append(("Invalid values", "packaging_weight", f"{len(bad_weights)} rows have zero or negative weight"))

# Inconsistent categorical labels (recyclable_flag)
if "recyclable_flag" in product_df.columns:
    flags = product_df["recyclable_flag"].dropna().astype(str).str.strip().unique().tolist()
    if len(flags) > 2:
        issues.append(("Inconsistent categorical labels", "recyclable_flag", f"Inconsistent values found: {flags}"))

# Jurisdiction spelling issues (simple heuristic: values that don't title-case cleanly or contain typos)
if "jurisdiction" in product_df.columns:
    jur_values = product_df["jurisdiction"].dropna().astype(str).str.strip().unique().tolist()
    issues.append(("Referential integrity (to be confirmed against fee table)", "jurisdiction", f"Distinct raw values: {jur_values}"))

if issues:
    issues_df = pd.DataFrame(issues, columns=["Category", "Column", "Detail"])
    st.dataframe(issues_df)
else:
    st.success("No obvious data quality issues detected by the automated checks.")

st.markdown("---")

st.subheader("Written assessment")

st.markdown(
    """
**1. What data quality issues do you see?**

| Category | Example in this dataset |
|---|---|
| Missing values | `packaging_weight`, `jurisdiction`, and `recyclable_flag` are blank on some rows (e.g. SKU-1012, SKU-1005, SKU-1031) |
| Inconsistent categorical labels | `recyclable_flag` mixes `Y` / `yes` / `N` / blank; `material_description` uses inconsistent free text (`PET`, `plastic - PET`, `rPET (30% recycled)`) for the same underlying material |
| Duplicate records | The same `sku` appears from more than one `source_system` (e.g. SKU-1001 from both ERP and Supplier) with slightly different `last_updated` timestamps and material descriptions |
| Unit inconsistencies | `packaging_weight` is reported in both grams and kilograms depending on the row, with no reliable per-source pattern |
| Referential integrity | `jurisdiction` values don't always match the fee rate table's country names exactly (e.g. `Belguim` vs `Belgium`) |
| Invalid values | A few rows have zero or negative `packaging_weight`, which is physically impossible |

**2. Blocking vs. assumption-based issues**

- **Blocking** (must be resolved before reporting a number to a regulator):
  - Missing or non-positive `packaging_weight` — there is no defensible way to estimate a specific product's
    physical packaging weight from other columns.
  - Missing `jurisdiction` — the entire point of EPR reporting is jurisdiction-specific liability; a number
    with no jurisdiction can't be attributed to the correct regulator.
  - `material_description` values that map to no recognized category and aren't clearly "Other" — reporting an
    unclassified material under an arbitrary category risks materially misstating the liability by category.
- **Can be handled with a documented assumption**:
  - Duplicate SKUs across source systems — resolved by taking the most recently updated record (documented
    precedence rule, see the Clean & Standardize page).
  - Unit inconsistency (g vs kg) — resolved by unit conversion, since the underlying physical weight is
    unambiguous once the unit is known.
  - Minor jurisdiction misspellings (`Belguim` → `Belgium`) — resolved by fuzzy-matching against the known
    jurisdiction list from the fee rate table, since the intended value is unambiguous.
  - Inconsistent `recyclable_flag` labels — normalized to Y/N/Unknown; this field doesn't currently feed the
    fee calculation, so it's a lower-stakes cleanup.

**3. If you had to ship a compliance report today**

I would report the fee liability computed only from records that pass all validation rules (see the Fee
Calculation page), and separately deliver the Exceptions report as an appendix — explicitly listing every
excluded SKU, its reason code, and its raw source data. This keeps the headline number defensible (nothing in
it is guessed) while being transparent about what's excluded and why, so the business can decide whether to
chase down the missing data before the regulatory deadline or accept the reported number as a conservative
floor. I would **not** silently impute missing weights or force-fit an ambiguous material into a category
just to make the total look complete, since a wrong number reported to a regulator is worse than a
transparently incomplete one.
"""
)
