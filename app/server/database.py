from __future__ import annotations

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from .config.settings import DatabaseSettings, ServerSettings


def _build_url(settings: DatabaseSettings, db_name: str) -> str:
    drive = settings.drive.lower()
    user = quote_plus(settings.user)
    password = quote_plus(settings.password)
    host = settings.host
    port = settings.resolved_port
    charset = settings.charset

    if drive == "mysql":
        return f"mysql+pymysql://{user}:{password}@{host}:{port}/{db_name}?charset={charset}"
    if drive == "sqlserver":
        # Using pymssql driver string
        return f"mssql+pymssql://{user}:{password}@{host}:{port}/{db_name}"
    if drive == "sqlite":
        if not settings.sqlite_dir:
            raise ValueError("sqlite_dir must be provided when drive=sqlite")
        sqlite_path = (settings.sqlite_dir / f"{db_name}.db").resolve()
        # SQLAlchemy expects forward slashes in SQLite URLs on Windows.
        return f"sqlite+pysqlite:///{sqlite_path.as_posix()}"
    raise ValueError(f"Unsupported database driver: {drive}")


def _create_engine(url: str):
    connect_args = {}
    if url.startswith("sqlite"):
        # FastAPI may use threadpool workers; allow SQLite connections across threads.
        connect_args = {"check_same_thread": False}
    return create_engine(url, pool_pre_ping=True, future=True, connect_args=connect_args)


def _create_sessionmaker(url: str):
    engine = _create_engine(url)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@dataclass(frozen=True)
class SessionRegistry:
    main: sessionmaker
    defect: sessionmaker
    management: sessionmaker


def _make_registry(settings: ServerSettings) -> SessionRegistry:
    main_db = settings.database.database_type or "ncdplate"
    defect_db = f"{main_db}defect"
    management_db = settings.database.management_database
    main_url = _build_url(settings.database, main_db)
    defect_url = _build_url(settings.database, defect_db)
    management_url = _build_url(settings.database, management_db)
    return SessionRegistry(
        main=_create_sessionmaker(main_url),
        defect=_create_sessionmaker(defect_url),
        management=_create_sessionmaker(management_url),
    )


_REGISTRY_CACHE: dict[str, SessionRegistry] = {}


def get_session_registry(settings: ServerSettings) -> SessionRegistry:
    """
    Build or retrieve cached session factories for the given settings.
    """
    signature = settings.model_dump_json()
    cached = _REGISTRY_CACHE.get(signature)
    if cached:
        return cached
    registry = _make_registry(settings)
    _REGISTRY_CACHE[signature] = registry
    return registry


def get_main_session(settings: ServerSettings):
    registry = get_session_registry(settings)
    return registry.main()


def get_defect_session(settings: ServerSettings):
    registry = get_session_registry(settings)
    return registry.defect()


def get_management_session(settings: ServerSettings):
    registry = get_session_registry(settings)
    return registry.management()


def ensure_database_exists(settings: DatabaseSettings, db_name: str) -> None:
    drive = settings.drive.lower()
    if drive == "sqlite":
        if settings.sqlite_dir:
            settings.sqlite_dir.mkdir(parents=True, exist_ok=True)
        return
    user = quote_plus(settings.user)
    password = quote_plus(settings.password)
    host = settings.host
    port = settings.resolved_port
    if drive == "mysql":
        url = f"mysql+pymysql://{user}:{password}@{host}:{port}/"
        engine = _create_engine(url)
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{db_name}` DEFAULT CHARACTER SET {settings.charset}"
                )
            )
        engine.dispose()
        return
    if drive == "sqlserver":
        url = f"mssql+pymssql://{user}:{password}@{host}:{port}/master"
        engine = _create_engine(url)
        with engine.begin() as connection:
            connection.execute(
                text(f"IF DB_ID(N'{db_name}') IS NULL CREATE DATABASE [{db_name}]")
            )
        engine.dispose()
        return
    raise ValueError(f"Unsupported database driver: {drive}")
