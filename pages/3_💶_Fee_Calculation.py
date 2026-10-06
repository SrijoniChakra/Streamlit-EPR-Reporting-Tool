import pandas as pd
import streamlit as st

st.set_page_config(page_title="Fee Calculation", page_icon="💶", layout="wide")
st.title("💶 Part 2.2 — EPR Fee Calculation")

result = st.session_state.get("pipeline_result")

if result is None:
    st.warning("No pipeline results yet. Go to the **Home** page, upload both files, and click **Run pipeline**.")
    st.stop()

summary = result["summary"]

if summary.empty:
    st.info("No records passed validation, so there is no fee liability to report. Check the Exceptions page.")
    st.stop()

st.markdown(
    "**Total EPR fee liability per jurisdiction × material category**, calculated as "
    "`packaging_weight_kg × fee_per_kg_local_currency`, summed across all accepted SKUs."
)

st.dataframe(
    summary.style.format({"total_fee_liability": "{:.5f}", "total_weight_kg": "{:.3f}"}),
)

grand_total = summary["total_fee_liability"].sum()
st.metric("Grand total liability across all jurisdictions & categories", f"{grand_total:,.5f}")

if result["stats"].get("total_liability_by_currency"):
    st.caption("Note: totals mix currencies across jurisdictions — see breakdown below.")
    st.write(result["stats"]["total_liability_by_currency"])

st.markdown("---")

col1, col2 = st.columns(2)
with col1:
    st.subheader("By jurisdiction")
    by_jur = summary.groupby("jurisdiction")["total_fee_liability"].sum().sort_values(ascending=False)
    st.bar_chart(by_jur)
with col2:
    st.subheader("By material category")
    by_cat = summary.groupby("category")["total_fee_liability"].sum().sort_values(ascending=False)
    st.bar_chart(by_cat)

st.markdown("---")
st.download_button(
    "⬇️ Download fee summary (CSV)",
    summary.to_csv(index=False).encode("utf-8"),
    file_name="epr_fee_summary.csv",
    mime="text/csv",
)
