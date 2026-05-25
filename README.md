# Royalty Normalize — Validation Prototype

Throwaway Streamlit app for prospect conversations. Drag-drop royalty
statements, get normalized XLSX outputs. Single-page, shared password,
no accounts or persistence.

## Local run

```bash
cd streamlit-prototype
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Set a password (or skip to run open locally)
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Edit secrets.toml and set APP_PASSWORD to something memorable

streamlit run app.py
# Opens http://localhost:8501
```

Upload one of your real royalty files (DPA.csv, IMAGO.xlsx, etc.) and verify
the output matches what the Python CLI produces.

## Deploy to Streamlit Community Cloud (free)

1. **Push to GitHub.** Repo: <https://github.com/ghowardMSD/streamlit-prototype>
   ```
   cd ~/Downloads/Zuma/streamlit-prototype
   git init
   git add app.py normalize.py registry.json requirements.txt \
           .streamlit/config.toml .streamlit/secrets.toml.example \
           .gitignore README.md
   git commit -m "validation prototype"
   git branch -M main
   git remote add origin https://github.com/ghowardMSD/streamlit-prototype.git
   git push -u origin main
   ```
   The `.gitignore` keeps `secrets.toml` (with your real password) out of the
   repo. Only `secrets.toml.example` is committed.

2. **Connect to Streamlit Community Cloud.** Go to
   <https://share.streamlit.io>, click **New app**, point at the repo,
   set the main file to `app.py`.

3. **Set the password.** In the app's **Advanced settings → Secrets**, paste:
   ```toml
   APP_PASSWORD = "your-real-password-here"
   ```
   Click Save. The app picks it up from `st.secrets["APP_PASSWORD"]`.

4. **Deploy.** Click Deploy. You'll get a URL like
   `https://<repo-name>.streamlit.app`. Share that URL plus the password with
   the prospects you've lined up.

Total time: 10–15 minutes. Total cost: $0.

## Updating the registry

`registry.json` is the agency catalog. Add an entry to support a new
reseller's format (see `references/extending.md` in the parent folder for
the schema and worked examples). For unknown formats during a demo, the app
will flag the file as "unrecognized" — make a note, ask the prospect to
share an example, add the entry later, redeploy.

## What this prototype does NOT do

These are intentional omissions for validation. Build them in
`BUILD_PLAN.md` Phase 1 after the SaaS premise is confirmed:

- Multi-tenant accounts (single shared password instead)
- LLM-powered proposer for unknown formats (manual cataloging instead)
- Customer-defined target schema (uses the canonical 11 columns)
- Persistence (process and forget)
- Audit trail
- Billing
- Chat interface

If a prospect asks for any of these, that's a positive signal — note it in
your conversation writeup.

## Notes for the demo call

- Open the URL fresh before the call, log in, and have an example file
  ready to demo if the prospect doesn't bring their own.
- Walk through one of *their* files if they're willing to share — much
  more compelling than seeing your own data processed.
- After the demo, close the laptop and listen. The prospect's reaction
  in the next 30 seconds is the signal you came for.
