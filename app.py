"""
Royalty Normalize — validation prototype.

Throwaway Streamlit app for showing the normalization tool to prospects.
Single page, drag-drop upload, shared password gate. Deploy free to Streamlit
Community Cloud; share the URL on prospect calls. See README.md for setup.
"""

from __future__ import annotations

import io
import json
import os
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from normalize import TARGET_COLS, identify_file, run_loader

VERSION = "1.5"

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Normalize Royalties",
    page_icon="📊",
    layout="centered",
)

# ---------------------------------------------------------------------------
# Password gate
# ---------------------------------------------------------------------------
def _get_password():
    # Streamlit Cloud Secrets first, then env var fallback for local dev.
    try:
        return st.secrets["APP_PASSWORD"]
    except (KeyError, FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return os.environ.get("APP_PASSWORD", "")


def check_password() -> bool:
    expected = _get_password()
    if not expected:
        # If no password configured, run open (useful for local dev only).
        return True
    if st.session_state.get("authed"):
        return True
    pw = st.text_input("Access Password", type="password")
    if pw and pw == expected:
        st.session_state["authed"] = True
        st.rerun()
    elif pw:
        st.error("Incorrect password.")
    return False


# ---------------------------------------------------------------------------
# Cached registry load
# ---------------------------------------------------------------------------
def load_registry() -> dict:
    return json.loads(Path("registry.json").read_text())


# ---------------------------------------------------------------------------
# Output writer
# ---------------------------------------------------------------------------
def df_to_xlsx_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="Sheet1", index=False)
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if not check_password():
    st.stop()

st.title("Normalize Royalties")
st.caption(
    "Drop royalty/usage statements from your resellers (CSV, XLSX, PDF). "
    "We identify the agency format, parse the rows, and produce a normalized "
    "spreadsheet ready for your backend."
)

with st.sidebar:
    st.header("Settings")
    eur_usd = st.number_input(
        "EUR → USD exchange rate",
        min_value=0.5, max_value=2.0, value=1.10, step=0.01,
        help="Used to convert EUR-denominated amounts to USD in the output.",
    )
    registry = load_registry()
    st.markdown(
        "**Known formats:** "
        + ", ".join(a["name"] for a in registry["agencies"])
    )
    st.caption(
        "Files not matching a known format are skipped. New formats are added "
        "by the team — share an example and we'll catalog it."
    )
    st.divider()
    st.caption(f"v{VERSION}")

uploads = st.file_uploader(
    "Drop statement files here",
    type=["csv", "xlsx", "xls", "pdf"],
    accept_multiple_files=True,
)

if not uploads:
    st.info("Drag-and-drop one or more royalty statement files to begin.")
    st.stop()

if "results" not in st.session_state:
    st.session_state["results"] = {}

if st.button("Process", type="primary", use_container_width=True):
    st.session_state["results"] = {}
    registry = load_registry()
    progress = st.progress(0.0, text="Identifying files…")
    total = len(uploads)

    for i, f in enumerate(uploads):
        progress.progress((i) / total, text=f"Processing {f.name}…")
        buf = f.getvalue()
        agency = identify_file(buf, f.name, registry)
        if agency is None:
            st.session_state["results"][f.name] = {
                "status": "unknown",
                "message": "Format not recognized. We don't have a parser for this agency yet.",
            }
            continue
        try:
            df = run_loader(agency["loader"], buf, f.name, agency.get("config", {}), eur_usd)
            df = df.copy()
            df["AMOUNT IN USD"] = pd.to_numeric(df["AMOUNT IN USD"], errors="coerce").round(2)
            df["EXCHANGE RATE"] = pd.to_numeric(df["EXCHANGE RATE"], errors="coerce").round(4)
            xlsx = df_to_xlsx_bytes(df)
            today = date.today().isoformat()
            safe_name = "".join(c if c.isalnum() else "_" for c in agency["name"])
            st.session_state["results"][f.name] = {
                "status": "ok",
                "agency": agency["name"],
                "rows": len(df),
                "total_usd": float(pd.to_numeric(df["AMOUNT IN USD"], errors="coerce").sum()),
                "output_name": f"{safe_name}_normalized_{today}.xlsx",
                "output_bytes": xlsx,
            }
        except Exception as e:
            st.session_state["results"][f.name] = {
                "status": "error",
                "agency": agency["name"],
                "message": f"{type(e).__name__}: {e}",
            }
    progress.progress(1.0, text="Done.")

if st.session_state["results"]:
    st.subheader("Results")
    grand_total = 0.0
    for fname, r in st.session_state["results"].items():
        with st.container(border=True):
            cols = st.columns([3, 1])
            with cols[0]:
                if r["status"] == "ok":
                    st.markdown(f"**{fname}** → identified as **{r['agency']}**")
                    st.markdown(f"{r['rows']} rows · ${r['total_usd']:,.2f} USD")
                    grand_total += r["total_usd"]
                elif r["status"] == "unknown":
                    st.markdown(f"**{fname}** — _unrecognized format_")
                    st.caption(r["message"])
                else:
                    st.markdown(f"**{fname}** — _error during processing_")
                    st.caption(r["message"])
            with cols[1]:
                if r["status"] == "ok":
                    st.download_button(
                        "Download",
                        data=r["output_bytes"],
                        file_name=r["output_name"],
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                        key=f"dl-{fname}",
                    )
    if grand_total:
        st.success(f"Combined total: **${grand_total:,.2f} USD** across all processed files.")

st.divider()
st.caption(
    "This is a working prototype. Production would add: per-customer accounts, "
    "your own target schema, learning new agency formats automatically, and "
    "an audit trail."
)
