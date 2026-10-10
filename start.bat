@echo off
REM One command: creates the virtual environment on first run, then serves the dashboard at http://localhost:8000
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Creating the virtual environment ^(first run only^)...
  py -3.12 -m venv .venv 2>nul || py -3.11 -m venv .venv || python -m venv .venv
  .venv\Scripts\python.exe -m pip install -q -r requirements.txt
)
if not exist data\cache\runs\N\run.json (
  echo Building the cached scenarios...
  .venv\Scripts\python.exe -m dt.api rebuild
)
if not exist web\dist\index.html (
  where npm >nul 2>nul && ( echo Building the dashboard... & pushd web & call npm install --no-audit --no-fund & call npm run build & popd ) || echo The dashboard build is missing and Node is not installed: only the API will run.
)
echo Dashboard: http://localhost:8000
.venv\Scripts\python.exe -m uvicorn server.app:app --port 8000
