@echo off
setlocal

echo [info] Starting Figmaaidefectdetectionsystem dev server...

rem Go to repo root, then into the Figma UI project
pushd "%~dp0"
cd /d "link_project\Figmaaidefectdetectionsystem" || (
  echo [error] Figmaaidefectdetectionsystem project not found under link_project.
  popd
  exit /b 1
)

if not exist "package.json" (
  echo [error] package.json not found in Figmaaidefectdetectionsystem.
  popd
  exit /b 1
)

if not exist "node_modules" (
  echo [info] node_modules not found. Running npm install...
  npm install
  if errorlevel 1 (
    echo [error] npm install failed.
    popd
    exit /b 1
  )
)

echo [info] Running: npm run dev
npm run dev

popd
endlocal

