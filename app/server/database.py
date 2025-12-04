from __future__ import annotations

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote_plus

from sqlalchemy import create_engine
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
    raise ValueError(f"Unsupported database driver: {drive}")


def _create_sessionmaker(url: str):
    engine = create_engine(url, pool_pre_ping=True, future=True)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@dataclass(frozen=True)
class SessionRegistry:
    main: sessionmaker
    defect: sessionmaker


def _make_registry(settings: ServerSettings) -> SessionRegistry:
    main_db = settings.database.database_type or "ncdplate"
    defect_db = f"{main_db}defect"
    main_url = _build_url(settings.database, main_db)
    defect_url = _build_url(settings.database, defect_db)
    return SessionRegistry(
        main=_create_sessionmaker(main_url),
        defect=_create_sessionmaker(defect_url),
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
