#!/bin/sh
# One-command launcher for the PII/PHI flagging & redaction app.
# Creates .venv on first run, installs requirements, then starts Streamlit.
set -e
cd "$(dirname "$0")"

# Skip Streamlit's first-run email prompt by opting out up front (empty email
# is the documented opt-out). Keeps the app air-gapped: no telemetry, nothing sent.
CRED_DIR="${HOME}/.streamlit"
if [ ! -f "${CRED_DIR}/credentials.toml" ]; then
  mkdir -p "${CRED_DIR}"
  printf '[general]\nemail = ""\n' > "${CRED_DIR}/credentials.toml"
fi

PY="${PYTHON:-python3}"
if [ ! -d .venv ]; then
  echo "First run: creating .venv and installing dependencies..."
  "$PY" -m venv .venv
fi
./.venv/bin/pip install --quiet --disable-pip-version-check -r requirements.txt

echo "Starting PII/PHI Flagging Engine at http://localhost:${PORT:-8502}"
exec ./.venv/bin/streamlit run phi_app.py --server.port "${PORT:-8502}" "$@"
