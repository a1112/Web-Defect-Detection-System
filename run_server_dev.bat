@echo off
setlocal

echo [info] Starting Web Defect Detection API server (dev, auto-reload)...

rem Run from repository root
pushd "%~dp0"

if not exist "configs\server.json" (
  echo [error] configs\server.json not found. Please create it or copy from configs\server.sample.json.
  popd
  exit /b 1
)

echo [info] Using config: configs\server.json

rem Enable auto-reload via env and flag
set BKJC_API_RELOAD=true
python app\server\main.py --config configs\server.json --host 0.0.0.0 --port 8120 --reload

popd
endlocal

