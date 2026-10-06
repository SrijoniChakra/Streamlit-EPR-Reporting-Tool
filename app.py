import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).parent))
from utils.pipeline import run_pipeline

st.set_page_config(page_title="EPR Reporting Tool", page_icon="♻️", layout="wide")

# ---------------------------------------------------------------------------
# Session state — this is the single source of truth for uploaded data and
# pipeline results. Every page reads from here instead of re-reading the
# file uploader widgets, so nothing disappears when you navigate away and
# come back (Streamlit resets widget state on page navigation, but NOT
# st.session_state).
# ---------------------------------------------------------------------------
defaults = {
    "product_df": None,
    "product_filename": None,
    "fee_df": None,
    "fee_filename": None,
    "pipeline_result": None,
}
for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value

st.title("♻️ EPR Reporting Tool")
st.caption(
    "Turn fragmented supply-chain extracts into an auditable Extended Producer "
    "Responsibility (EPR) fee report."
)

st.markdown(
    """
Upload your two source files below:

1. **Product extract** (`sample_products.csv`) — merged rows from ERP, supplier portal, and a manual
   compliance spreadsheet, with the usual mess: mixed units, inconsistent material labels,
   duplicate SKUs, and missing/misspelled jurisdictions.
2. **Fee rate table** (`fee_rates.csv`) — per-kg EPR fee by jurisdiction and material category.

No demo data is preloaded — nothing is processed until you upload your own files.
"""
)

col1, col2 = st.columns(2)

with col1:
    st.subheader("1. Product extract")
    product_file = st.file_uploader(
        "Upload product extract (CSV)", type=["csv"], key="product_uploader"
    )
    if product_file is not None:
        st.session_state["product_df"] = pd.read_csv(product_file)
        st.session_state["product_filename"] = product_file.name
        st.session_state["pipeline_result"] = None  # invalidate stale results

    if  st.session_state["product_df"] is not None:
        st.success(f"Loaded **{st.session_state['product_filename']}** — {len(st.session_state['product_df'])} rows")
        st.dataframe(st.session_state["product_df"].head(10))
    else:
        st.info("No product file uploaded yet.")

with col2:
    st.subheader("2. Fee rate table")
    fee_file = st.file_uploader(
        "Upload fee rate table (CSV)", type=["csv"], key="fee_uploader"
    )
    if fee_file is not None:
        st.session_state["fee_df"] = pd.read_csv(fee_file)
        st.session_state["fee_filename"] = fee_file.name
        st.session_state["pipeline_result"] = None

    if st.session_state["fee_df"] is not None:
        st.success(f"Loaded **{st.session_state['fee_filename']}** — {len(st.session_state['fee_df'])} rows")
        st.dataframe(st.session_state["fee_df"].head(10))
    else:
        st.info("No fee rate file uploaded yet.")

st.markdown("---")

files_ready = st.session_state["product_df"] is not None and st.session_state["fee_df"] is not None

run_col, clear_col = st.columns([1, 1])

with run_col:
    if st.button("▶️ Run pipeline", disabled=not files_ready):
        try:
            with st.spinner("Cleaning, deduplicating, and calculating fees..."):
                result = run_pipeline(st.session_state["product_df"], st.session_state["fee_df"])
            st.session_state["pipeline_result"] = result
            st.success("Pipeline run complete — use the pages in the sidebar to explore the results.")
        except ValueError as e:
            st.error(str(e))

with clear_col:
    if st.button("🗑️ Clear all uploaded files"):
        for key in defaults:
            st.session_state[key] = None
        st.rerun()

if not files_ready:
    st.warning("Upload both files above to enable the pipeline.")
elif st.session_state["pipeline_result"] is None:
    st.info("Files are loaded. Click **Run pipeline** to clean the data and calculate EPR fees.")
else:
    stats = st.session_state["pipeline_result"]["stats"]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Raw rows uploaded", stats["raw_rows"])
    m2.metric("Duplicate SKUs resolved", stats["duplicate_skus_resolved"])
    m3.metric("Clean rows (fee calculated)", stats["clean_rows"])
    m4.metric("Rows flagged as exceptions", stats["exception_rows"])
    st.success("Pipeline results are ready. Use the sidebar to view Data Quality, Cleaning, Fee Calculation, Exceptions, and Audit Trail.")

st.markdown("---")
st.markdown(
    """
**Pages (see sidebar):**
- 📋 **Data Quality Assessment** — Part 1 write-up plus auto-detected issues in your uploaded file
- 🧹 **Clean & Standardize** — unit conversion, category mapping, jurisdiction matching, dedup logic
- 💶 **Fee Calculation** — total EPR liability per jurisdiction × material category
- ⚠️ **Exceptions** — every record that couldn't be confidently processed, with a reason code
- 🔍 **Audit Trail** — row-level lineage from source record to final output
"""
)
