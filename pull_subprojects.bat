@echo off
setlocal

echo [info] Syncing and updating Git submodules...

rem Run from repository root
pushd "%~dp0"

git submodule sync --recursive
if errorlevel 1 (
  echo [error] Failed to sync submodules.
  popd
  exit /b 1
)

git submodule update --init --recursive
if errorlevel 1 (
  echo [error] Failed to update submodules.
  popd
  exit /b 1
)

echo [ok] Subprojects updated.

popd
endlocal

