# Royalty Normalize

A single-page Streamlit app that normalizes royalty/usage statements from
multiple agency formats (CSV, XLSX, XLS, PDF) into a standard spreadsheet.
Drag-drop one or more files, the app identifies each format, parses the rows,
and produces a normalized XLSX for download. Access is gated by a shared
password; files are processed in memory and not persisted.

## Local run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Optional: set an access password (leave unset to run open locally)
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Edit secrets.toml and set APP_PASSWORD

streamlit run app.py
# Opens http://localhost:8501
```

## Deploy to Streamlit Community Cloud

1. **Push to GitHub** (the `.gitignore` keeps `secrets.toml` and any local
   sample data out of the repo).
2. **Create the app** at <https://share.streamlit.io> → **New app**, point it
   at this repo, and set the main file to `app.py`.
3. **Set the password.** In **Advanced settings → Secrets**, add:
   ```toml
   APP_PASSWORD = "your-password-here"
   ```
4. **Deploy.** You'll get a `https://<app-name>.streamlit.app` URL.

The version number shown in the sidebar reflects the deployed build — bump
`VERSION` in `app.py` when shipping a change to confirm the deploy took.

## Supported formats

The app recognizes nine agency statement formats. Files that don't match a
known format are flagged as unrecognized and skipped.

## Adding a format

`registry.json` is the format catalog. Each entry defines how to identify a
file (filename patterns + a header fingerprint) and which loader parses it.
Clean tabular files can use the config-driven `generic` loader via field
mappings; irregular layouts (multi-line PDFs, offset headers) get a custom
loader function in `normalize.py`. Add the entry, add a loader if needed, and
redeploy.

## Output schema

Each file is normalized to 11 columns: `INVOICE NUMBER`, `COUNTRY`, `CLIENT`,
`ZUMA FILE NUMBER`, `ORIGINAL FILE NUMBER`, `DESCRIPTION`, `PHOTOGRAPHER`,
`PHOTOG CODE`, `FOREIGN CURRENCY`, `EXCHANGE RATE`, `AMOUNT IN USD`.

EUR-denominated amounts are converted to USD using the exchange rate set in
the sidebar.
