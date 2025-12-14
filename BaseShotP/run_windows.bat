@echo off
setlocal
cd /d %~dp0
if not exist ".venv" (
  py -m venv .venv
)
call .venv\Scripts\activate
python -m pip install --upgrade pip >nul
pip install -r requirements.txt
if not exist ".env" (
  copy .env.example .env >nul
  echo Created .env (please set BASE_RPC_URL inside it)
)
python app.py
endlocal
