import pandas as pd
import streamlit as st

st.set_page_config(page_title="Exceptions", page_icon="⚠️", layout="wide")
st.title("⚠️ Part 2.3 — Exceptions")

result = st.session_state.get("pipeline_result")

if result is None:
    st.warning("No pipeline results yet. Go to the **Home** page, upload both files, and click **Run pipeline**.")
    st.stop()

exceptions_df = result["exceptions"]

if exceptions_df.empty:
    st.success("No exceptions — every uploaded row was cleanly processed.")
    st.stop()

st.markdown(
    "Every record below could **not** be confidently processed into the fee calculation. "
    "Each row has a `reason_code` explaining why, plus the original raw values for follow-up."
)

reason_counts = exceptions_df["reason_code"].value_counts()
st.subheader("Reason code breakdown")
st.bar_chart(reason_counts)

reason_legend = {
    "MISSING_SKU": "SKU is blank — record can't be identified or deduplicated.",
    "MISSING_WEIGHT": "packaging_weight is blank.",
    "UNRECOGNIZED_UNIT": "weight_unit isn't a recognized spelling of grams or kilograms.",
    "NON_POSITIVE_WEIGHT": "packaging_weight is zero or negative.",
    "UNMAPPABLE_MATERIAL": "material_description is blank or 'unknown' — can't assign a category.",
    "UNMAPPABLE_JURISDICTION": "jurisdiction doesn't match any jurisdiction in the fee rate table, even with fuzzy matching.",
    "NO_MATCHING_FEE_RATE": "jurisdiction and category are both valid, but the fee rate table has no rate defined for that combination.",
}
with st.expander("Reason code legend"):
    for code, desc in reason_legend.items():
        if code in reason_counts.index:
            st.write(f"**{code}** — {desc}")

st.markdown("---")

selected_reasons = st.multiselect(
    "Filter by reason code",
    options=sorted(exceptions_df["reason_code"].unique()),
    default=sorted(exceptions_df["reason_code"].unique()),
)
filtered = exceptions_df[exceptions_df["reason_code"].isin(selected_reasons)]

st.dataframe(
    filtered[["source_row_id", "source_system", "sku", "reason_code", "detail"]]
)

with st.expander("View raw source record for a specific row"):
    row_ids = filtered["source_row_id"].tolist()
    if row_ids:
        picked = st.selectbox("Choose a row", row_ids)
        raw = filtered[filtered["source_row_id"] == picked]["raw_record"].iloc[0]
        st.json(raw)

st.markdown("---")
st.download_button(
    "⬇️ Download exceptions report (CSV)",
    filtered.drop(columns=["raw_record"]).to_csv(index=False).encode("utf-8"),
    file_name="epr_exceptions.csv",
    mime="text/csv",
)
