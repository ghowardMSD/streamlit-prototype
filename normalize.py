"""
Royalty statement normalization engine — adapted from normalize_royalty.py to
work with in-memory buffers (BytesIO) instead of file paths. Suitable for
Streamlit, FastAPI, or any web context where uploads arrive as bytes.

Public surface:
    TARGET_COLS                          — the 11-column backend schema
    identify_file(buf, name, registry)   — match a file to a registry entry
    run_loader(name, buf, fname, cfg, r) — execute the named loader
    LOADERS                              — name -> callable map
"""

from __future__ import annotations

import fnmatch
import io
import re
from collections import defaultdict
from typing import Any

import pandas as pd
import pdfplumber

ZUMA_FN_RE = re.compile(r"(\d{8}_[a-z]{3}_[a-z]{1,3}\d{1,3}_\d+(?:\.\w+)?)", re.IGNORECASE)

TARGET_COLS = [
    "INVOICE NUMBER", "COUNTRY", "CLIENT", "ZUMA FILE NUMBER",
    "ORIGINAL FILE NUMBER", "DESCRIPTION", "PHOTOGRAPHER", "PHOTOG CODE",
    "FOREIGN CURRENCY", "EXCHANGE RATE", "AMOUNT IN USD",
]

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def to_num(s):
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().replace("\xa0", "").replace(" ", "").replace("$", "")
    s = s.replace("%", "")
    if "," in s and "." in s:
        if s.find(",") < s.find("."):
            s = s.replace(",", "")
        else:
            s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def photog_code(name):
    if not name or (isinstance(name, float) and pd.isna(name)):
        return ""
    name = str(name).strip()
    if not name:
        return ""
    primary = re.split(r"[/\\]", name)[0].strip()
    parts = [p for p in re.split(r"\s+", primary) if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0][:4].upper()
    return "".join(p[0] for p in parts[:3]).upper()


def _bio(buf: bytes | io.BytesIO) -> io.BytesIO:
    """Return a fresh BytesIO regardless of input flavor."""
    if isinstance(buf, io.BytesIO):
        buf.seek(0)
        return buf
    return io.BytesIO(buf)


def resolve_value(v, rate):
    if v == "@EUR_USD":
        return rate
    return v


# ---------------------------------------------------------------------------
# generic loader (config-driven, for clean CSV/XLSX)
# ---------------------------------------------------------------------------
def generic_loader(buf, fname, config, rate):
    fmt = config.get("format", "csv")
    bio = _bio(buf)
    if fmt == "csv":
        df = pd.read_csv(bio, dtype=str, **config.get("csv_options", {}))
    elif fmt == "xlsx":
        df = pd.read_excel(bio, **config.get("xlsx_options", {}))
    else:
        raise ValueError(f"unsupported format: {fmt}")

    out = pd.DataFrame(index=df.index)
    for target in TARGET_COLS:
        rule = config.get("mapping", {}).get(target, {"value": ""})
        out[target] = _apply_rule(rule, df, rate)
    return out


def _apply_rule(rule, df, rate):
    if "value" in rule:
        return resolve_value(rule["value"], rate)
    if "field" in rule:
        s = df[rule["field"]].astype(str)
        if rule.get("transform") == "rstrip_comma_strip":
            s = s.str.rstrip(",").str.strip()
        if rule.get("number"):
            nums = s.map(to_num)
            if rule.get("times_rate"):
                nums = nums * rate
            return nums
        return s
    if "derive" in rule:
        d = rule["derive"]
        if d.startswith("photog_code_from:"):
            return df[d.split(":", 1)[1]].map(photog_code)
        if d.startswith("zuma_file_number_from:"):
            col = d.split(":", 1)[1]
            return df[col].astype(str).str.extract(ZUMA_FN_RE.pattern, flags=re.IGNORECASE, expand=False).fillna("")
    raise ValueError(f"unknown rule: {rule}")


# ---------------------------------------------------------------------------
# custom loaders (ported from normalize_royalty.py)
# ---------------------------------------------------------------------------
def load_imago(buf, fname, config, rate):
    df = pd.read_excel(_bio(buf), sheet_name=config.get("sheet", "Worksheet"))
    out = pd.DataFrame()
    out["INVOICE NUMBER"] = df["id (intern)"].astype(str).str.replace(".0", "", regex=False)
    out["COUNTRY"] = config.get("default_country", "Germany")
    out["CLIENT"] = df["client"]

    def find_zuma(ref, desc, img):
        for src in (ref, desc):
            if isinstance(src, str) and src.strip():
                m = ZUMA_FN_RE.search(src)
                if m: return m.group(1)
        if isinstance(ref, str) and ref.strip():
            return re.sub(r"\s*Copyright:.*$", "", ref).strip(" -")
        if pd.notna(img):
            return str(img).replace(".0", "")
        return ""

    out["ZUMA FILE NUMBER"] = [
        find_zuma(r, d, n) for r, d, n in
        zip(df["reference"], df["description"], df["IMAGO image number"])
    ]
    out["ORIGINAL FILE NUMBER"] = df["original file name"].fillna("").astype(str)
    out["DESCRIPTION"] = df["description"].fillna("").astype(str)
    out["PHOTOGRAPHER"] = df["credit"].fillna("").astype(str)
    out["PHOTOG CODE"] = df["credit"].map(photog_code)
    out["FOREIGN CURRENCY"] = config.get("default_currency", "EUR")
    out["EXCHANGE RATE"] = rate
    out["AMOUNT IN USD"] = df["amount EUR"].map(to_num) * rate
    return out


def load_cordon(buf, fname, config, rate):
    raw = pd.read_excel(_bio(buf), sheet_name=0, header=None)
    invoice_no = ""
    for i in range(min(15, len(raw))):
        row_str = " ".join(str(x) for x in raw.iloc[i].tolist() if pd.notna(x))
        m = re.search(r"Sales Report Nr\.?\s*:?\s*(\d+)", row_str)
        if m:
            invoice_no = m.group(1)
            break
    data = raw.iloc[12:].copy()
    data.columns = ["InvCode", "CustNr", "Description", "Qu", "Unit",
                    "Price", "Com", "Amount"]
    data = data[data["Description"].notna() & (data["Description"].astype(str).str.strip() != "")]
    data = data[~data["Description"].astype(str).str.lower().str.contains("total", na=False)]
    data = data[data["Amount"].apply(lambda x: to_num(x) is not None)]
    out = pd.DataFrame()
    out["INVOICE NUMBER"] = data["InvCode"].astype(str).str.replace(".0", "", regex=False)
    out["COUNTRY"] = config.get("default_country", "Spain")
    out["CLIENT"] = config.get("default_client", "CORDON PRESS S.L.")
    out["ZUMA FILE NUMBER"] = data["Description"].astype(str).str.extract(ZUMA_FN_RE.pattern, flags=re.IGNORECASE, expand=False).fillna("")
    out["ORIGINAL FILE NUMBER"] = ""
    out["DESCRIPTION"] = ""
    out["PHOTOGRAPHER"] = ""
    out["PHOTOG CODE"] = ""
    out["FOREIGN CURRENCY"] = config.get("default_currency", "EUR")
    out["EXCHANGE RATE"] = rate
    out["AMOUNT IN USD"] = data["Price"].map(to_num) * rate
    return out.reset_index(drop=True)


def load_abaca(buf, fname, config, rate):
    rows = []
    invoice_no = ""
    default_pct = config.get("default_commission_pct", 60.0)
    with pdfplumber.open(_bio(buf)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            m = re.search(r"Relev[ée]\s*N[°o]\s*(\S+)", text)
            if m and not invoice_no:
                invoice_no = m.group(1)
            words = page.extract_words(use_text_flow=False)
            row_buckets = defaultdict(list)
            for w in words:
                row_buckets[round(w["top"] / 2) * 2].append(w)
            for _, ws in sorted(row_buckets.items()):
                ws.sort(key=lambda w: w["x0"])
                if not ws or not re.match(r"^\d+_\d+$", ws[0]["text"]):
                    continue
                our_ref = ws[0]["text"]
                rest = ws[1:]
                ref_source = ""
                if rest and 60 < rest[0]["x0"] < 130:
                    ref_source = rest[0]["text"]
                    rest = rest[1:]
                zuma_file = ""
                if rest and 165 < rest[0]["x0"] < 200:
                    zuma_file = rest[0]["text"]
                else:
                    for w in rest:
                        if re.match(r"\d{8}_[a-z]{3}_", w["text"], re.IGNORECASE):
                            zuma_file = w["text"]
                            break
                share_w = ws[-1] if ws[-1]["x0"] > 640 else None
                share_val = to_num(share_w["text"]) if share_w else None
                pct_val = None
                for w in ws:
                    if 600 < w["x0"] < 640:
                        m = re.search(r"(\d{1,3}[.,]\d{2})", w["text"])
                        if m:
                            pct_val = to_num(m.group(1))
                            break
                if pct_val is None:
                    pct_val = default_pct
                montant = share_val / (pct_val / 100.0) if share_val and pct_val else None
                subj = [w["text"] for w in ws if 285 < w["x0"] < 575]
                rows.append({
                    "INVOICE NUMBER": invoice_no,
                    "COUNTRY": config.get("default_country", "France"),
                    "CLIENT": config.get("default_client", "ABACA"),
                    "ZUMA FILE NUMBER": zuma_file,
                    "ORIGINAL FILE NUMBER": ref_source or our_ref,
                    "DESCRIPTION": " ".join(subj).strip(),
                    "PHOTOGRAPHER": "",
                    "PHOTOG CODE": "",
                    "FOREIGN CURRENCY": config.get("default_currency", "EUR"),
                    "EXCHANGE RATE": rate,
                    "AMOUNT IN USD": (montant or 0) * rate,
                })
    return pd.DataFrame(rows)


def load_rea(buf, fname, config, rate):
    rows = []
    invoice_no = ""
    with pdfplumber.open(_bio(buf)) as pdf:
        full_text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    m = re.search(r"Relev[ée]\s*N[°o]?\s*(\S+)", full_text)
    if m:
        invoice_no = m.group(1).rstrip(":")
    blocks = re.split(r"(?=^Client\s*:)", full_text, flags=re.MULTILINE)
    for block in blocks:
        if not block.strip().startswith("Client"):
            continue
        lines = block.strip().splitlines()
        client_line = lines[0]
        tail = re.search(r"([\d.,]+)\s+([\d.,]+)\s*%?\s+([\d.,]+)\s*$", client_line)
        if not tail:
            continue
        gross = tail.group(1)
        head = client_line[:tail.start()].strip()
        cm = re.search(r"Client\s*:\s*-\s*([^-]+?)\s*-", head)
        client = cm.group(1).strip() if cm else ""
        ref = credit = legend = ""
        for ln in lines[1:]:
            ln = ln.strip()
            if ln.startswith("Référence"):
                ref = re.sub(r"^Référence\s*:\s*", "", ln).strip()
            elif ln.startswith("Crédit"):
                credit = re.sub(r"^Crédit\s*:\s*", "", ln).strip()
            elif ln.startswith("Légende"):
                legend = re.sub(r"^Légende\s*:\s*", "", ln).strip()
        fn = re.search(
            r"(\d{8}_[a-z]{3}_[a-zA-Z]\d{1,3}_\d+(?:\.\w+)?|rea_\d+_\d+(?:\.\w+)?|REA_\d+_\d+)",
            ref, re.IGNORECASE,
        )
        zuma_file = fn.group(1) if fn else ref
        rows.append({
            "INVOICE NUMBER": invoice_no,
            "COUNTRY": config.get("default_country", "France"),
            "CLIENT": client,
            "ZUMA FILE NUMBER": zuma_file,
            "ORIGINAL FILE NUMBER": "",
            "DESCRIPTION": legend,
            "PHOTOGRAPHER": credit,
            "PHOTOG CODE": photog_code(credit),
            "FOREIGN CURRENCY": config.get("default_currency", "EUR"),
            "EXCHANGE RATE": rate,
            "AMOUNT IN USD": (to_num(gross) or 0) * rate,
        })
    return pd.DataFrame(rows)


def load_picvario(buf, fname, config, rate):
    # Header is at a fixed row; data follows until "Total sales" footer rows.
    header_row = config.get("header_row", 7)
    df = pd.read_excel(_bio(buf), sheet_name=0, header=header_row)
    df.columns = [str(c).strip() for c in df.columns]
    img = df["Image"].astype(str)
    # Keep only real image rows (drops "Total sales" / share footer rows).
    df = df[img.str.extract(ZUMA_FN_RE.pattern, flags=re.IGNORECASE, expand=False).notna()].copy()
    out = pd.DataFrame(index=df.index)
    out["INVOICE NUMBER"] = ""
    out["COUNTRY"] = config.get("default_country", "Russia")
    out["CLIENT"] = df["Company"].fillna("").astype(str)
    out["ZUMA FILE NUMBER"] = df["Image"].astype(str).str.extract(
        ZUMA_FN_RE.pattern, flags=re.IGNORECASE, expand=False).fillna("")
    out["ORIGINAL FILE NUMBER"] = df["Original"].fillna("").astype(str)
    out["DESCRIPTION"] = ""
    out["PHOTOGRAPHER"] = df["Author"].fillna("").astype(str)
    out["PHOTOG CODE"] = df["Author"].map(photog_code)
    out["FOREIGN CURRENCY"] = config.get("default_currency", "USD")
    out["EXCHANGE RATE"] = config.get("exchange_rate", 1.0)
    out["AMOUNT IN USD"] = df["Cost, USD"].map(to_num) * config.get("exchange_rate", 1.0)
    return out.reset_index(drop=True)


def load_contacto(buf, fname, config, rate):
    raw = pd.read_excel(_bio(buf), sheet_name=0, header=None)
    header_row = config.get("header_row", 4)
    data = raw.iloc[header_row + 1:].copy()
    # Columns by position: Publication, Subject, Photographer, Total, Share, Zuma file.
    data.columns = [f"c{i}" for i in range(data.shape[1])]
    fn = data["c5"].astype(str)
    data = data[fn.str.extract(ZUMA_FN_RE.pattern, flags=re.IGNORECASE, expand=False).notna()].copy()
    out = pd.DataFrame(index=data.index)
    out["INVOICE NUMBER"] = ""
    out["COUNTRY"] = config.get("default_country", "Spain")
    out["CLIENT"] = data["c0"].fillna("").astype(str)
    out["ZUMA FILE NUMBER"] = data["c5"].astype(str).str.extract(
        ZUMA_FN_RE.pattern, flags=re.IGNORECASE, expand=False).fillna("")
    out["ORIGINAL FILE NUMBER"] = ""
    out["DESCRIPTION"] = data["c1"].fillna("").astype(str)
    out["PHOTOGRAPHER"] = data["c2"].fillna("").astype(str)
    out["PHOTOG CODE"] = data["c2"].map(photog_code)
    out["FOREIGN CURRENCY"] = config.get("default_currency", "EUR")
    out["EXCHANGE RATE"] = rate
    out["AMOUNT IN USD"] = data["c3"].map(to_num) * rate
    return out.reset_index(drop=True)


def _group_lines(words, tol=2):
    """Group words into visual lines bucketed by `top`, each sorted left-to-right."""
    buckets = defaultdict(list)
    for w in words:
        buckets[round(w["top"] / tol) * tol].append(w)
    return [sorted(ws, key=lambda w: w["x0"]) for _, ws in sorted(buckets.items())]


def load_bestimage(buf, fname, config, rate):
    # Wrapped multi-line table. Columns identified by x0; each record begins on the
    # line carrying the country + Montant/%/Droits values, then wraps below.
    cols = {
        "client": (0, 76), "photo": (76, 143), "ref": (143, 210),
        "sujet": (210, 345), "auteur": (345, 390), "montant": (435, 480),
    }
    rows = []
    invoice_no = ""

    def is_start(ln):
        has_montant = any(435 <= w["x0"] < 480 and to_num(w["text"]) is not None for w in ln)
        has_droits = any(w["x0"] >= 524 and ("€" in w["text"] or to_num(w["text"]) is not None) for w in ln)
        return has_montant and has_droits

    def flush(rec):
        if not rec:
            return
        col_words = {k: [w for ln in rec for w in ln if lo <= w["x0"] < hi]
                     for k, (lo, hi) in cols.items()}
        # Filename and photo-number columns wrap vertically — join without spaces.
        ref_join = "".join(w["text"] for w in col_words["ref"])
        m = ZUMA_FN_RE.search(ref_join)
        montant = next((to_num(w["text"]) for w in rec[0]
                        if 435 <= w["x0"] < 480 and to_num(w["text"]) is not None), None)
        auteur = " ".join(w["text"] for w in col_words["auteur"]).strip()
        rows.append({
            "INVOICE NUMBER": invoice_no,
            "COUNTRY": config.get("default_country", "France"),
            "CLIENT": " ".join(w["text"] for w in col_words["client"]).strip(),
            "ZUMA FILE NUMBER": m.group(1) if m else ref_join,
            "ORIGINAL FILE NUMBER": "".join(w["text"] for w in col_words["photo"]),
            "DESCRIPTION": " ".join(w["text"] for w in col_words["sujet"]).strip(),
            "PHOTOGRAPHER": auteur,
            "PHOTOG CODE": photog_code(auteur),
            "FOREIGN CURRENCY": config.get("default_currency", "EUR"),
            "EXCHANGE RATE": rate,
            "AMOUNT IN USD": (montant or 0) * rate,
        })

    with pdfplumber.open(_bio(buf)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if not invoice_no:
                m = re.search(r"N[°o]\s*(\d+)", text)
                if m:
                    invoice_no = m.group(1)
            cur = None
            for ln in _group_lines(page.extract_words(use_text_flow=False)):
                if is_start(ln):
                    flush(cur)
                    cur = [ln]
                elif cur is not None:
                    # Stop accumulating at a totals/footer line outside the data columns.
                    if any("total" in w["text"].lower() for w in ln):
                        flush(cur)
                        cur = None
                    else:
                        cur.append(ln)
            flush(cur)
    return pd.DataFrame(rows)


def load_dana(buf, fname, config, rate):
    # Wrapped multi-line table, but every field we need sits on the record-start
    # line (the one ending in an amount + "$"). Amounts are already USD.
    rows = []
    invoice_no = ""
    with pdfplumber.open(_bio(buf)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if not invoice_no:
                m = re.search(r"Sales Report No\.?\s*(\S+)", text)
                if m:
                    invoice_no = m.group(1)
            for ln in _group_lines(page.extract_words(use_text_flow=False)):
                amt_w = next((w for w in ln if w["x0"] > 530 and to_num(w["text"]) is not None), None)
                has_dollar = any(w["text"] == "$" and w["x0"] > 555 for w in ln)
                if amt_w is None or not has_dollar:
                    continue
                line_text = " ".join(w["text"] for w in ln)
                fn = ZUMA_FN_RE.search(line_text)
                photog = " ".join(w["text"] for w in ln if 108 <= w["x0"] < 196).strip(" /")
                media_no = next((w["text"] for w in ln if 196 <= w["x0"] < 233 and to_num(w["text"]) is not None), "")
                ref_no = next((w["text"] for w in ln if 450 <= w["x0"] < 520 and to_num(w["text"]) is not None), "")
                rows.append({
                    "INVOICE NUMBER": invoice_no,
                    "COUNTRY": config.get("default_country", "Denmark"),
                    "CLIENT": config.get("default_client", "DANA PRESS"),
                    "ZUMA FILE NUMBER": fn.group(1) if fn else "",
                    "ORIGINAL FILE NUMBER": ref_no,
                    "DESCRIPTION": "",
                    "PHOTOGRAPHER": photog,
                    "PHOTOG CODE": photog_code(photog),
                    "FOREIGN CURRENCY": config.get("default_currency", "USD"),
                    "EXCHANGE RATE": config.get("exchange_rate", 1.0),
                    "AMOUNT IN USD": (to_num(amt_w["text"]) or 0) * config.get("exchange_rate", 1.0),
                })
    return pd.DataFrame(rows)


LOADERS = {
    "generic": generic_loader,
    "imago": load_imago,
    "cordon": load_cordon,
    "picvario": load_picvario,
    "contacto": load_contacto,
    "bestimage": load_bestimage,
    "dana": load_dana,
    "abaca": load_abaca,
    "rea": load_rea,
}


# ---------------------------------------------------------------------------
# identification
# ---------------------------------------------------------------------------
def _read_header_sample(buf, fname, max_rows=30):
    ext = fname.lower().rsplit(".", 1)[-1] if "." in fname else ""
    bio = _bio(buf)
    try:
        if ext == "csv":
            text = bio.read().decode("utf-8", errors="replace")
            lines = text.splitlines()[:max_rows]
            return [t for ln in lines for t in re.split(r"[;,\t]", ln.strip())]
        if ext in ("xlsx", "xls"):
            raw = pd.read_excel(bio, sheet_name=0, header=None, nrows=max_rows)
            return [str(c) for c in raw.values.flatten() if pd.notna(c)]
        if ext == "pdf":
            with pdfplumber.open(bio) as pdf:
                if pdf.pages:
                    text = pdf.pages[0].extract_text() or ""
                    return text.splitlines()
    except Exception:
        return []
    return []


def identify_file(buf, fname, registry):
    candidates = []
    fname_lower = fname.lower()
    for agency in registry.get("agencies", []):
        for p in agency["identify"].get("filename_patterns", []):
            if fnmatch.fnmatch(fname, p) or fnmatch.fnmatch(fname_lower, p.lower()):
                candidates.append(agency)
                break
    if len(candidates) == 1:
        return candidates[0]
    pool = candidates if candidates else registry.get("agencies", [])
    sample = _read_header_sample(buf, fname)
    sample_joined = " ".join(sample)
    for agency in pool:
        fp = agency["identify"].get("header_fingerprint")
        if not fp:
            continue
        if all(any(t in s for s in sample) or t in sample_joined for t in fp):
            return agency
    return None


def run_loader(loader_name: str, buf, fname: str, config: dict, rate: float):
    fn = LOADERS.get(loader_name)
    if fn is None:
        raise ValueError(f"unknown loader: {loader_name}")
    df = fn(buf, fname, config, rate)
    return df[TARGET_COLS]
