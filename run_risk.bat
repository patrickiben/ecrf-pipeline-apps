@echo off
rem One-command launcher for Participant risk screening, risk_app.py (Windows).
rem Creates .venv on first run, installs requirements, then starts Streamlit.
setlocal
cd /d "%~dp0"

rem Skip Streamlit's first-run email prompt by opting out up front (empty email
rem is the documented opt-out). Keeps the app air-gapped: no telemetry, nothing sent.
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
  if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
  >"%USERPROFILE%\.streamlit\credentials.toml" echo [general]
  >>"%USERPROFILE%\.streamlit\credentials.toml" echo email = ""
)

if not exist ".venv\Scripts\python.exe" (
  echo First run: creating .venv and installing dependencies...
  python -m venv .venv || goto :err
)
".venv\Scripts\pip.exe" install --quiet --disable-pip-version-check -r requirements.txt || goto :err

if "%PORT%"=="" set PORT=8503
echo Starting Participant risk screening [risk_app.py] at http://localhost:%PORT%
".venv\Scripts\streamlit.exe" run risk_app.py --server.port %PORT% %*
exit /b 0
:err
echo Launcher failed. See messages above.
exit /b 1
