from __future__ import annotations

from bkjc_database import CONFIG, core
from bkjc_database.dbm import get_dbm

from .config.settings import DatabaseSettings, ServerSettings


class DatabaseBootstrap:
    def __init__(self, settings: DatabaseSettings):
        self.settings = settings
        self._config = None
        self._db = None

    def connect(self):
        drive = self.settings.drive.lower()
        base_url = core.setBaseUrl(
            ip=self.settings.host,
            port=self.settings.resolved_port,
            user=self.settings.user,
            password=self.settings.password,
            chart=self.settings.charset,
            drive_=drive,
        )
        if drive == "mysql":
            config = CONFIG.DbConfig4d0()
        else:
            config = CONFIG.DbConfig3d0()
        config.baseUrl = base_url
        if hasattr(config, "database_type"):
            setattr(config, "database_type", self.settings.database_type)
        self._config = config
        self._db = get_dbm(config, reGet=True)
        return self._db

    @property
    def db(self):
        if self._db is None:
            return self.connect()
        return self._db


_DB_CACHE: dict[str, object] = {}


def _settings_signature(settings: ServerSettings) -> str:
    return settings.model_dump_json()


def get_database(settings: ServerSettings):
    signature = _settings_signature(settings)
    cached = _DB_CACHE.get(signature)
    if cached is not None:
        return cached
    bootstrap = DatabaseBootstrap(settings.database)
    db = bootstrap.db
    _DB_CACHE[signature] = db
    return db
