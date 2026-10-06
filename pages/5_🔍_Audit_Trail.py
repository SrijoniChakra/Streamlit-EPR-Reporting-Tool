import streamlit as st

st.set_page_config(page_title="Audit Trail", page_icon="🔍", layout="wide")
st.title("🔍 Part 2.4 — Audit Trail")

result = st.session_state.get("pipeline_result")

if result is None:
    st.warning("No pipeline results yet. Go to the **Home** page, upload both files, and click **Run pipeline**.")
    st.stop()

st.markdown(
    """
**Modeling choice:** lineage is captured as a separate **long-format audit log** (one row per transformation
applied), keyed by `source_row_id` and `sku`, rather than a single lineage string crammed into the main output
table. Reasons:

- The *number* of transformations applied differs per row (a row might only need a unit conversion, or it might
  need unit conversion + category mapping + jurisdiction fuzzy-match + dedup resolution) — a fixed lineage
  column can't cleanly hold a variable-length list without becoming hard to query.
- A long format lets you filter to, say, *"show me every row where jurisdiction was fuzzy-matched"* with a
  simple filter, instead of parsing a semicolon-delimited string.
- `source_row_id` ties every audit entry back to the exact upload row (see the Exceptions page for the raw
  record itself), so any output number can be fully reconstructed: which source row(s) fed it, and what rule
  changed each field along the way.
"""
)

audit_log = result["audit_log"]

if audit_log.empty:
    st.info("No transformations were logged (nothing needed cleaning).")
    st.stop()

col1, col2 = st.columns(2)
with col1:
    sku_filter = st.text_input("Filter by SKU (exact match, optional)")
with col2:
    field_filter = st.multiselect(
        "Filter by field",
        options=sorted(audit_log["field"].unique()),
        default=sorted(audit_log["field"].unique()),
    )

filtered = audit_log[audit_log["field"].isin(field_filter)]
if sku_filter:
    filtered = filtered[filtered["sku"].astype(str) == sku_filter]

st.dataframe(filtered)

st.download_button(
    "⬇️ Download full audit log (CSV)",
    audit_log.to_csv(index=False).encode("utf-8"),
    file_name="epr_audit_log.csv",
    mime="text/csv",
)
