@echo off
setlocal

echo [info] Starting Web Defect Detection API server (2D + SMALL)...

rem Run from repository root
pushd "%~dp0"

if not exist "configs\server.json" (
  echo [error] configs\server.json not found. Please create it or copy from configs\server.sample.json.
  popd
  exit /b 1
)

if not exist "configs\server_small.json" (
  echo [error] configs\server_small.json not found. Please create it or adjust image paths.
  popd
  exit /b 1
)

echo [info] Using config (2D):    configs\server.json
echo [info] Using config (SMALL): configs\server_small.json
echo.

rem Start 2D instance on port 8120
start "BKJC_API_2D" cmd /c python app\server\main.py --config configs\server.json --host 0.0.0.0 --port 8120 --workers 4

rem Start SMALL instance on port 8130 (image_root = /data/images/small)
start "BKJC_API_SMALL" cmd /c python app\server\main.py --config configs\server_small.json --host 0.0.0.0 --port 8130 --workers 4

popd
endlocal
