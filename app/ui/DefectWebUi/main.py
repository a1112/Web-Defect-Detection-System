from __future__ import annotations
import argparse
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _resolve_qml_entry() -> Path:
    here = Path(__file__).resolve().parent
    return here / "qml" / "App.qml"


def run() -> int:
    _configure_logging()

    parser = argparse.ArgumentParser(description="Launch DefectWebUi (Qt/QML) via PySide6.")
    parser.add_argument(
        "--api-base-url",
        default=os.getenv("DEFECT_API_BASE_URL", "http://127.0.0.1:8120"),
        help="Backend base URL (leave empty for same-origin).",
    )
    parser.add_argument(
        "--qt-platform",
        default=os.getenv("QT_QPA_PLATFORM", ""),
        help="Override Qt platform plugin (e.g. windows, offscreen).",
    )
    parser.add_argument(
        "--rhi-backend",
        default=os.getenv("QSG_RHI_BACKEND", ""),
        help="Override Qt Quick RHI backend (e.g. d3d11, opengl, software).",
    )
    parser.add_argument(
        "--quick-backend",
        default=os.getenv("QT_QUICK_BACKEND", ""),
        help="Override Qt Quick backend (e.g. software).",
    )
    parser.add_argument(
        "--debug-qt-plugins",
        action="store_true",
        default=os.getenv("QT_DEBUG_PLUGINS", "").strip() not in ("", "0", "false", "False"),
        help="Enable Qt plugin debug output (sets QT_DEBUG_PLUGINS=1).",
    )
    parser.add_argument(
        "--clean-qt-env",
        action="store_true",
        help="Unset common Qt/QML path env vars to avoid mixing multiple Qt installs.",
    )
    args = parser.parse_args()

    if args.clean_qt_env:
        for key in (
            "QML2_IMPORT_PATH",
            "QML_IMPORT_PATH",
            "QT_PLUGIN_PATH",
            "QT_QPA_PLATFORM_PLUGIN_PATH",
            "QT_QUICK_CONTROLS_STYLE",
        ):
            os.environ.pop(key, None)

    if args.debug_qt_plugins:
        os.environ["QT_DEBUG_PLUGINS"] = "1"
    if args.qt_platform:
        os.environ["QT_QPA_PLATFORM"] = args.qt_platform
    if args.rhi_backend:
        os.environ["QSG_RHI_BACKEND"] = args.rhi_backend
    if args.quick_backend:
        os.environ["QT_QUICK_BACKEND"] = args.quick_backend

    qml_entry = _resolve_qml_entry()
    if not qml_entry.exists():
        raise FileNotFoundError(f"QML entry not found: {qml_entry}")

    try:
        from PySide6.QtCore import QCoreApplication, QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine
    except Exception as exc:  # pragma: no cover
        logger.error("PySide6 is required to run the desktop UI: pip install PySide6")
        logger.exception(exc)
        return 2

    app = QGuiApplication(sys.argv)
    QCoreApplication.setOrganizationName("DefectWeb")
    QCoreApplication.setOrganizationDomain("example.local")
    QCoreApplication.setApplicationName("Defect Web UI")

    engine = QQmlApplicationEngine()
    engine.addImportPath(str(qml_entry.parent))
    engine.addImportPath(str(qml_entry.parent / "store"))
    engine.addImportPath(str(qml_entry.parent / "components"))
    engine.addImportPath(str(qml_entry.parent / "pages"))

    qml_warnings: list[str] = []

    def _log_qml_warnings(warnings) -> None:
        try:
            for warning in warnings:
                qml_warnings.append(warning.toString())
                logger.error("QML: %s", warning.toString())
        except Exception:
            logger.exception("Failed to log QML warnings")

    try:
        engine.warnings.connect(_log_qml_warnings)
    except Exception:
        pass
    if args.api_base_url:
        engine.rootContext().setContextProperty("DEFECT_API_BASE_URL", args.api_base_url)

    engine.load(QUrl.fromLocalFile(str(qml_entry)))
    if not engine.rootObjects():
        logger.error("Failed to load QML: %s", qml_entry)
        for warning in qml_warnings:
            logger.error("QML: %s", warning)
        return 1
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(run())
