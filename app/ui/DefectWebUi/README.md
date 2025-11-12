# Defect Web UI (Qt Quick + WebAssembly)

This directory hosts a lightweight Qt Quick interface that mirrors the layout patterns of the Copper UI project, but is trimmed down to the essentials required to preview inspection frames inside a WebAssembly build.

## Features

- Qt Quick Controls 2 + Material theme to stay close to the desktop UI
- Image URL handling is fully managed in QML, pulling frames over HTTP/S without requiring a C++ bridge
- `ImagePreview` component that shows loading/error states and can pull images from URLs or the built‑in placeholder
- Side rail + stacked content panes so we can extend to more tabs without restructuring
- All imports are versionless (`import QtQuick.Controls` instead of `import ... 2.15`) to avoid issues with Qt for WebAssembly kits
- Assets and QML are bundled via `qml/qml.qrc` and `resources/resources.qrc`, mirroring the reference Copper UI layout

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

- Replace the placeholder image by pointing the `Image` source directly to your backend（REST/WebSocket 生成的签名 URL 均可）。
- Drop additional tabs into `SideRail` and `StackLayout` and populate them with QML pages in `qml/components` or nested directories.
- Keep imports versionless and prefer `QtQuick.Controls.Material` styling to stay WASM-compatible.

## 与 FastAPI 服务集成

- `app.server.main` 会尝试从 `app/ui/DefectWebUi/build/WebAssembly_Qt_6_10_0_multi_threaded-MinSizeRel` 自动挂载 `/ui`。
- 如果你的 WASM 输出位于其他目录，启动服务前设置环境变量 `DEFECT_UI_BUILD_DIR` 指向该目录，例如：
  ```powershell
  $env:DEFECT_UI_BUILD_DIR = "J:\Web-Defect-Detection-System\app\ui\DefectWebUi\build\WebAssembly_Qt_6_10_0_multi_threaded-MinSizeRel"
  python -m app.server.main --host 0.0.0.0 --port 8000
  ```
- 启动后访问 `http://127.0.0.1:8000/ui/DefectWebUi.html`，前端与 `/api/...` 位于同源，QML 中可直接使用相对路径（如 `/api/images/mosaic?...`）避免 CORS。

## 启用 HTTPS（解决局域网 multi-threaded WASM 的 crossOrigin 限制）

1. 生成或准备证书/私钥（PEM）。例如使用 OpenSSL：
   ```powershell
   openssl req -x509 -newkey rsa:2048 -keyout server.key -out server.crt `
       -days 365 -nodes -subj "/CN=192.168.1.45"
   ```
2. 运行 FastAPI 时指定证书：
   ```powershell
   python -m app.server.main --host 0.0.0.0 --port 8000 `
       --ssl-certfile J:\certs\server.crt `
       --ssl-keyfile J:\certs\server.key
   ```
   也可以通过环境变量 `DEFECT_SSL_CERT` 和 `DEFECT_SSL_KEY` 提前配置。
3. 在浏览器/手机上访问 `https://<局域网IP>:8000/ui/DefectWebUi.html`，如果是自签证书需要先信任它。此时页面会满足安全上下文 + COOP/COEP，Qt WebAssembly 多线程可正常运行。
