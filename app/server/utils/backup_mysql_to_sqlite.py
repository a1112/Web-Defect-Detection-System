from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Iterable

from sqlalchemy import MetaData, Table, create_engine, select, text
from sqlalchemy.dialects import mysql
from sqlalchemy.sql import sqltypes

# Ensure repository root is on sys.path before importing app.*
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.server.config.settings import ENV_CONFIG_KEY, ServerSettings  # noqa: E402

logger = logging.getLogger(__name__)


def _build_mysql_url(settings: ServerSettings, db_name: str) -> str:
    database = settings.database
    drive = database.drive.lower()
    user = database.user
    password = database.password
    host = database.host
    port = database.resolved_port
    charset = database.charset

    if drive != "mysql":
        raise ValueError(f"Only mysql is supported for export, got {drive!r}")
    # Keep URL format aligned with app/server/database.py.
    # NOTE: pymysql is listed in requirements.txt.
    from urllib.parse import quote_plus

    return (
        "mysql+pymysql://"
        f"{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{db_name}"
        f"?charset={quote_plus(charset)}"
    )


def _sorted_tables(metadata: MetaData) -> Iterable[Table]:
    # Use SQLAlchemy's dependency ordering where possible.
    return metadata.sorted_tables


def _map_mysql_type_to_sqlite(type_):  # noqa: ANN001
    """
    MySQL reflection yields MySQL dialect types (e.g. mysql.TINYINT) which the
    SQLite compiler can't always render. Map them to generic SQLAlchemy types.
    """
    if isinstance(type_, mysql.TINYINT):
        # Commonly used as boolean(1) in MySQL schemas, but integer is safest.
        return sqltypes.Integer()
    if isinstance(type_, (mysql.SMALLINT, mysql.MEDIUMINT, mysql.INTEGER, mysql.BIGINT)):
        return sqltypes.Integer()
    if isinstance(type_, mysql.BIT):
        return sqltypes.Integer()
    if isinstance(type_, (mysql.FLOAT, mysql.DOUBLE, mysql.REAL)):
        return sqltypes.Float()
    if isinstance(type_, (mysql.DECIMAL, mysql.NUMERIC)):
        return sqltypes.Numeric(precision=getattr(type_, "precision", None), scale=getattr(type_, "scale", None))
    if isinstance(type_, (mysql.DATETIME, mysql.TIMESTAMP)):
        return sqltypes.DateTime()
    if isinstance(type_, mysql.DATE):
        return sqltypes.Date()
    if isinstance(type_, mysql.TIME):
        return sqltypes.Time()
    if isinstance(type_, (mysql.TEXT, mysql.TINYTEXT, mysql.MEDIUMTEXT, mysql.LONGTEXT)):
        return sqltypes.Text()
    if isinstance(type_, (mysql.VARCHAR, mysql.CHAR)):
        length = getattr(type_, "length", None)
        return sqltypes.String(length=length)
    if isinstance(type_, (mysql.BLOB, mysql.TINYBLOB, mysql.MEDIUMBLOB, mysql.LONGBLOB)):
        return sqltypes.LargeBinary()
    if isinstance(type_, (mysql.ENUM, mysql.SET)):
        return sqltypes.String()
    if isinstance(type_, mysql.JSON):
        return sqltypes.Text()
    return type_


def export_mysql_database_to_sqlite(
    *,
    source_url: str,
    sqlite_path: Path,
    batch_size: int = 2000,
    consistent_snapshot: bool = True,
) -> None:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    if sqlite_path.exists():
        sqlite_path.unlink()

    source_engine = create_engine(source_url, pool_pre_ping=True, future=True)
    sqlite_engine = create_engine(f"sqlite+pysqlite:///{sqlite_path}", future=True)

    source_metadata = MetaData()
    with source_engine.connect() as source_connection:
        source_metadata.reflect(bind=source_connection)

    sqlite_metadata = MetaData()
    used_index_names: set[str] = set()
    used_index_names_normalized: set[str] = set()
    for table in _sorted_tables(source_metadata):
        cloned = table.to_metadata(sqlite_metadata)
        for column in cloned.columns:
            column.type = _map_mysql_type_to_sqlite(column.type)
        for index in list(cloned.indexes):
            if not index.name:
                continue
            candidate = index.name
            if candidate.lower() in used_index_names_normalized:
                candidate = f"{cloned.name}_{index.name}"
            suffix = 1
            while candidate.lower() in used_index_names_normalized:
                candidate = f"{cloned.name}_{index.name}_{suffix}"
                suffix += 1
            if candidate != index.name:
                index.name = candidate
            used_index_names.add(candidate)
            used_index_names_normalized.add(candidate.lower())
    sqlite_metadata.create_all(sqlite_engine)

    with source_engine.connect().execution_options(stream_results=True) as source_connection:
        if consistent_snapshot:
            try:
                source_connection.exec_driver_sql("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                source_connection.exec_driver_sql("START TRANSACTION WITH CONSISTENT SNAPSHOT")
            except Exception:
                logger.exception("Failed to start consistent snapshot; falling back to normal reads.")

        with sqlite_engine.begin() as sqlite_connection:
            sqlite_connection.execute(text("PRAGMA foreign_keys=OFF"))
            sqlite_connection.execute(text("PRAGMA journal_mode=WAL"))
            sqlite_connection.execute(text("PRAGMA synchronous=NORMAL"))

            for source_table in _sorted_tables(source_metadata):
                dest_table = sqlite_metadata.tables[source_table.key]
                result = source_connection.execute(select(source_table))
                inserted = 0
                while True:
                    rows = result.fetchmany(batch_size)
                    if not rows:
                        break
                    sqlite_connection.execute(
                        dest_table.insert(),
                        [dict(row._mapping) for row in rows],
                    )
                    inserted += len(rows)
                logger.info("Exported %s: %d rows", source_table.name, inserted)

            sqlite_connection.execute(text("PRAGMA foreign_keys=ON"))

        if consistent_snapshot:
            try:
                source_connection.rollback()
            except Exception:
                logger.exception("Failed to rollback export snapshot transaction.")


def verify_sqlite(sqlite_path: Path) -> None:
    import sqlite3

    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite file not found: {sqlite_path}")
    con = sqlite3.connect(sqlite_path)
    try:
        result = con.execute("PRAGMA quick_check").fetchall()
        if not result or any(row[0] != "ok" for row in result):
            raise RuntimeError(f"SQLite quick_check failed for {sqlite_path}: {result}")
        tables = con.execute("select count(*) from sqlite_master where type='table'").fetchone()[0]
        logger.info("Verified %s (tables=%s)", sqlite_path.name, tables)
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Export current MySQL databases to SQLite3 backups")
    parser.add_argument("--config", help="Path to JSON config file (same as server)")
    parser.add_argument(
        "--out-dir",
        default=str(REPO_ROOT / "TestData" / "DataBase"),
        help="Output directory for sqlite .db files",
    )
    parser.add_argument("--batch-size", type=int, default=2000)
    parser.add_argument(
        "--no-consistent-snapshot",
        action="store_true",
        help="Disable MySQL consistent snapshot export (may be needed for non-InnoDB tables).",
    )
    parser.add_argument(
        "--only",
        choices=("main", "defect", "both"),
        default="both",
        help="Which database(s) to export.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify existing sqlite backups in --out-dir; do not export.",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip sqlite quick_check verification after export.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(levelname)s %(message)s")

    if args.config:
        os.environ[ENV_CONFIG_KEY] = str(Path(args.config).resolve())

    settings = ServerSettings.load(args.config)
    main_db = settings.database.database_type or "ncdplate"
    defect_db = f"{main_db}defect"

    out_dir = Path(args.out_dir)
    consistent_snapshot = not args.no_consistent_snapshot
    verify_after = not args.no_verify

    main_path = out_dir / f"{main_db}.db"
    defect_path = out_dir / f"{defect_db}.db"

    if args.verify_only:
        if args.only in ("main", "both"):
            verify_sqlite(main_path)
        if args.only in ("defect", "both"):
            verify_sqlite(defect_path)
        return 0

    if args.only in ("main", "both"):
        export_mysql_database_to_sqlite(
            source_url=_build_mysql_url(settings, main_db),
            sqlite_path=main_path,
            batch_size=args.batch_size,
            consistent_snapshot=consistent_snapshot,
        )
        if verify_after:
            verify_sqlite(main_path)

    if args.only in ("defect", "both"):
        export_mysql_database_to_sqlite(
            source_url=_build_mysql_url(settings, defect_db),
            sqlite_path=defect_path,
            batch_size=args.batch_size,
            consistent_snapshot=consistent_snapshot,
        )
        if verify_after:
            verify_sqlite(defect_path)

    logger.info("Done. SQLite backups written to %s", out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
