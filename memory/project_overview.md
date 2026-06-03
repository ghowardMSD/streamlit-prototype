---
name: project-overview
description: Royalty Normalize — Streamlit demo prototype for Zuma Press; normalizes photo-agency royalty statements to a standard schema
metadata:
  type: project
---

Throwaway Streamlit prototype for validating a royalty-normalization SaaS concept with prospects at Zuma Press (a photo agency). Deployed to Streamlit Community Cloud for live demos.

**Why:** Validate SaaS premise before building. README explicitly says "build in BUILD_PLAN.md Phase 1 after the SaaS premise is confirmed."

**How to apply:** Changes here are demo/prototype quality — keep it simple, no over-engineering. Intentional omissions (multi-tenant, LLM format discovery, persistence, billing) are features of the prototype, not gaps.

## Architecture
- `app.py` — Single-page Streamlit frontend; password gate → file upload → process button → results + download
- `normalize.py` — In-memory normalization engine; 6 loaders + file identification
- `registry.json` — Agency catalog (JSON-driven config; add entries to support new agencies)
- `requirements.txt` — 5 deps: streamlit, pandas, openpyxl, xlrd, pdfplumber

## Supported agencies (6)
| Agency | Format | Loader |
|---|---|---|
| DPA | CSV (semicolon) | generic |
| IMAGO | XLSX | custom |
| CORDON | XLSX | custom |
| ZUMA Royalty Output | XLS/XLSX | custom |
| ABACA | PDF (coordinate parsing) | custom |
| REA | PDF (regex text) | custom |

## Output schema (11 columns)
INVOICE NUMBER, COUNTRY, CLIENT, ZUMA FILE NUMBER, ORIGINAL FILE NUMBER, DESCRIPTION, PHOTOGRAPHER, PHOTOG CODE, FOREIGN CURRENCY, EXCHANGE RATE, AMOUNT IN USD

## File identification
Two-stage: filename pattern match first → if ambiguous, header fingerprint scan (first 30 rows/lines).
