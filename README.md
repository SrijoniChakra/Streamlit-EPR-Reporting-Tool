# EPR Reporting Tool

A Streamlit app implementing the take-home EPR (Extended Producer Responsibility) reporting exercise.

## Run it

```bash
pip install streamlit pandas
streamlit run app.py
```

## How to use it

1. On the **Home** page, upload your product extract CSV and your fee rate table CSV.
   Two example files with realistic messy data are included in `sample_data/` if you want to try
   the app before using your own files.
2. Click **Run pipeline**.
3. Use the sidebar pages to review:
   - **📋 Data Quality Assessment** — Part 1 write-up + auto-detected issues in your file
   - **🧹 Clean & Standardize** — unit conversion, category mapping, jurisdiction matching, dedup logic
   - **💶 Fee Calculation** — total EPR liability per jurisdiction × material category
   - **⚠️ Exceptions** — every record that couldn't be confidently processed, with a reason code
   - **🔍 Audit Trail** — row-level lineage from source record to final output

## Why files don't disappear when you switch pages

Uploaded data and pipeline results are stored in `st.session_state` (not read live from the
`st.file_uploader` widgets), so they persist across page navigation within the same browser
session. A **Clear all uploaded files** button on the Home page lets you reset deliberately.

## Design decisions (see the in-app pages for full explanations)

- **Dedup precedence**: most recent `last_updated` wins; ties broken by source trust order
  `ERP > Supplier > Manual`.
- **Unit conversion**: recognizes g/kg (and common spelling variants); anything else is flagged,
  never guessed.
- **Category mapping**: keyword-based lookup against a material category map; unmapped/blank
  descriptions are flagged rather than defaulted to a real category.
- **Jurisdiction matching**: fuzzy-matched (stdlib `difflib`) against the jurisdictions present in
  the uploaded fee rate table, to tolerate minor typos without an extra dependency.
- **Audit trail**: modeled as a separate long-format audit log (one row per transformation), keyed
  by a stable `source_row_id`, rather than a single lineage string column — see the Audit Trail page
  for the full justification.
