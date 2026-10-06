import streamlit as st

st.set_page_config(page_title="Clean & Standardize", page_icon="🧹", layout="wide")
st.title("🧹 Part 2.1 — Clean & Standardize")

result = st.session_state.get("pipeline_result")

if result is None:
    st.warning("No pipeline results yet. Go to the **Home** page, upload both files, and click **Run pipeline**.")
    st.stop()

st.markdown(
    """
This step applies four transformations to every uploaded row, in order, before anything is deduplicated or
fee-calculated. Each transformation is also written to the **Audit Trail** so it can be traced per row.
"""
)

with st.expander("1. Unit standardization", expanded=True):
    st.markdown(
        """
`packaging_weight` is converted to a single unit, **kg**, using the `weight_unit` column.
Recognized spellings: `kg`, `kgs`, `kilogram(s)`, `g`, `gram(s)`, `gm`. Any other unit, or a missing weight,
is **not guessed** — it's flagged as an exception instead.
        """
    )

with st.expander("2. Material category mapping"):
    from utils.pipeline import CATEGORY_MAP
    st.markdown("`material_description` is matched (case-insensitive, substring match) against these keyword groups:")
    st.json(CATEGORY_MAP)
    st.markdown(
        "Anything not matched, but with a non-empty description, is bucketed as **Other** (matches the fee "
        "table's `Other` rate). A blank/unknown description is bucketed as **Unmapped** and flagged as an exception, "
        "since reporting an unclassified material as a real category risks misstating the fee by category."
    )

with st.expander("3. Jurisdiction standardization"):
    st.markdown(
        """
`jurisdiction` is matched against the list of jurisdictions present in the uploaded fee rate table, using
fuzzy string matching (Python's built-in `difflib`, cutoff similarity 0.6). This catches minor typos
(e.g. `Belguim` → `Belgium`) without needing an extra fuzzy-matching library. A value with no match above
the cutoff is left unmapped and flagged as an exception rather than silently discarded or guessed.
        """
    )

with st.expander("4. Deduplication across source systems"):
    st.markdown(
        """
**Precedence rule (documented assumption):** when the same `sku` appears more than once (e.g. from ERP,
the supplier portal, and a manual spreadsheet), the record with the most recent `last_updated` timestamp is
kept. If two records share the same timestamp, ties are broken by source trust order:
**ERP > Supplier > Manual**. All discarded duplicate rows are recorded in the Audit Trail, referencing which
row was kept and why.
        """
    )
    dedup_notes = result.get("dedup_notes", {})
    if dedup_notes:
        st.write(f"**{len(dedup_notes)} SKU(s) had duplicate records resolved this run:**")
        for sku, info in dedup_notes.items():
            st.write(
                f"- `{sku}`: kept **{info['kept_source']}** ({info['kept_row_id']}), "
                f"discarded {info['discarded_sources']} ({info['discarded_row_ids']})"
            )
    else:
        st.write("No duplicate SKUs were found in this upload.")

st.markdown("---")
st.subheader("Cleaned, fee-calculated output")
st.caption("This is the accepted dataset — rows that passed every validation rule. Rows that didn't are on the Exceptions page.")
st.dataframe(result["clean"])

st.download_button(
    "⬇️ Download cleaned dataset (CSV)",
    result["clean"].to_csv(index=False).encode("utf-8"),
    file_name="epr_cleaned_products.csv",
    mime="text/csv",
)
