# Defect Web UI (Qt Quick + WebAssembly)

This directory hosts a lightweight Qt Quick interface that mirrors the layout patterns of the Copper UI project, but is trimmed down to the essentials required to preview inspection frames inside a WebAssembly build.

## Features

- Qt Quick Controls 2 + Material theme to stay close to the desktop UI
- `FrameBridge` C++ stub that exposes a `sourceUrl` property to QML, keeping the wiring ready for future camera/image providers
- `ImagePreview` component that shows loading/error states and can pull images from URLs or the built‑in placeholder
- Side rail + stacked content panes so we can extend to more tabs without restructuring
- All imports are versionless (`import QtQuick.Controls` instead of `import ... 2.15`) to avoid issues with Qt for WebAssembly kits

## Building (Desktop or WebAssembly)

1. Configure
   ```bash
   cmake -S app/ui/DefectWebUi -B build/defect-ui -G "Ninja" ^
         -DCMAKE_BUILD_TYPE=RelWithDebInfo
   ```
   For WebAssembly, point CMake to the Qt for WASM toolchain:
   ```bash
   cmake -S app/ui/DefectWebUi -B build/defect-ui-wasm -G "Ninja" ^
         -DCMAKE_TOOLCHAIN_FILE=%QT_WASM_ROOT%/lib/cmake/Qt6/qt.toolchain.cmake
   ```
   (replace `%QT_WASM_ROOT%` with the Qt installation path that was built with emscripten/wasm).

2. Build
   ```bash
   cmake --build build/defect-ui
   ```
   or `build/defect-ui-wasm` for the wasm target. Qt will emit the `DefectWebUi.html`/`wasm` artifacts.

3. Run
   - Desktop: `build/defect-ui/DefectWebUi`
   - WebAssembly: serve the output directory over HTTP (`python -m http.server` is sufficient) and open the generated HTML.

## Extending

- Replace the placeholder image by wiring `FrameBridge` to your vision backend (REST, WebSocket, or shared memory).
- Drop additional tabs into `SideRail` and `StackLayout` and populate them with QML pages in `qml/components` or nested directories.
- Keep imports versionless and prefer `QtQuick.Controls.Material` styling to stay WASM‑compatible.
