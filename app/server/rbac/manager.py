# coding: utf-8
from __future__ import annotations

import json
import secrets
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.server.config.settings import ServerSettings
from app.server.database import _build_url, _create_engine, ensure_database_exists
from app.server.db.models import rbac as rbac_models

REPO_ROOT = Path(__file__).resolve().parents[3]
CASBIN_MODEL_PATH = REPO_ROOT / "configs" / "casbin" / "model.conf"
_INIT_LOCK = threading.Lock()
_INIT_DONE: set[str] = set()

DEFAULT_UI_CONFIG = {
    "themePreset": "industrial-blue",
    "customTheme": False,
    "theme": "dark",
    "language": "zh-CN",
    "fontSize": 14,
    "compactMode": True,
    "showGridLines": True,
    "animationSpeed": 300,
    "primaryColor": "#3b82f6",
    "accentColor": "#8b5cf6",
    "autoRefreshInterval": 30,
}

DEFAULT_MOCKDATA_CONFIG = {
    "config": {
        "steelPlateCount": 50,
        "defectCountRange": [5, 30],
        "defectTypes": ["划伤", "气泡", "裂纹", "夹杂", "氧化铁"],
        "severityDistribution": {"critical": 10, "major": 30, "minor": 60},
        "imageCount": 10,
        "autoGenerateInterval": 0,
    },
    "templates": [
        {
            "id": "1",
            "name": "深度划伤",
            "type": "划伤",
            "severity": "critical",
            "minSize": 50,
            "maxSize": 200,
        },
        {
            "id": "2",
            "name": "表面气泡",
            "type": "气泡",
            "severity": "minor",
            "minSize": 10,
            "maxSize": 40,
        },
        {
            "id": "3",
            "name": "边缘裂纹",
            "type": "裂纹",
            "severity": "major",
            "minSize": 30,
            "maxSize": 150,
        },
    ],
}


def initialize_management_database(settings: ServerSettings) -> None:
    db_name = settings.database.management_database
    ensure_database_exists(settings.database, db_name)
    engine = _create_engine(_build_url(settings.database, db_name))
    rbac_models.Base.metadata.create_all(engine, checkfirst=True)
    engine.dispose()


def bootstrap_management(settings: ServerSettings, session: Session) -> None:
    bind_url = str(session.get_bind().engine.url)
    with _INIT_LOCK:
        if bind_url not in _INIT_DONE:
            initialize_management_database(settings)
            _INIT_DONE.add(bind_url)
    ensure_admin_user(session)
    ensure_casbin_seed(session)


def _hash_password(password: str, salt: str) -> str:
    import hashlib

    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000
    ).hex()


def ensure_admin_user(session: Session) -> None:
    admin_name = "admin"
    admin_password = "Nercar701"

    def _get_role() -> rbac_models.Role | None:
        return session.execute(
            select(rbac_models.Role).where(rbac_models.Role.name == "admin")
        ).scalar_one_or_none()

    def _ensure_role() -> rbac_models.Role:
        role = _get_role()
        if role:
            return role
        role = rbac_models.Role(name="admin", description="System administrators")
        session.add(role)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            role = _get_role()
            if role:
                return role
            raise
        return role

    existing = session.execute(
        select(rbac_models.User).where(rbac_models.User.username == admin_name)
    ).scalar_one_or_none()
    if existing:
        role = _ensure_role()
        if not existing.roles:
            session.add(rbac_models.UserRole(user_id=existing.id, role_id=role.id))
            session.commit()
        return

    salt = secrets.token_hex(16)
    password_hash = _hash_password(admin_password, salt)
    user = rbac_models.User(
        username=admin_name,
        password_hash=password_hash,
        password_salt=salt,
        is_active=True,
        is_superuser=True,
    )
    session.add(user)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        existing = session.execute(
            select(rbac_models.User).where(rbac_models.User.username == admin_name)
        ).scalar_one_or_none()
        if not existing:
            raise
        role = _ensure_role()
        if not existing.roles:
            session.add(rbac_models.UserRole(user_id=existing.id, role_id=role.id))
            session.commit()
        return

    role = _ensure_role()
    link = rbac_models.UserRole(user_id=user.id, role_id=role.id)
    session.add(link)
    session.commit()


def ensure_casbin_seed(session: Session) -> None:
    try:
        from casbin import Enforcer
        from casbin_sqlalchemy_adapter import Adapter
    except ImportError:
        return

    adapter = Adapter(session.get_bind())
    enforcer = Enforcer(str(CASBIN_MODEL_PATH), adapter)
    if not enforcer.has_policy("role_admin", "*", "*"):
        enforcer.add_policy("role_admin", "*", "*")
    if not enforcer.has_grouping_policy("admin", "role_admin"):
        enforcer.add_grouping_policy("admin", "role_admin")
    enforcer.save_policy()


def validate_login(session: Session, username: str, password: str) -> dict[str, Any] | None:
    user = session.execute(
        select(rbac_models.User).where(rbac_models.User.username == username)
    ).scalar_one_or_none()
    if not user or not user.is_active:
        return None
    password_hash = _hash_password(password, user.password_salt)
    if password_hash != user.password_hash:
        return None
    role = None
    if user.roles:
        role = user.roles[0].name
    return {"username": user.username, "role": role or "operator", "is_superuser": user.is_superuser}


def get_config(session: Session, key: str, fallback: dict[str, Any]) -> dict[str, Any]:
    entry = session.execute(
        select(rbac_models.ConfigEntry).where(rbac_models.ConfigEntry.config_key == key)
    ).scalar_one_or_none()
    if not entry:
        return fallback
    try:
        return json.loads(entry.config_value)
    except json.JSONDecodeError:
        return fallback


def set_config(session: Session, key: str, payload: dict[str, Any]) -> None:
    value = json.dumps(payload, ensure_ascii=False)
    entry = session.execute(
        select(rbac_models.ConfigEntry).where(rbac_models.ConfigEntry.config_key == key)
    ).scalar_one_or_none()
    if entry:
        entry.config_value = value
        entry.updated_at = datetime.utcnow()
    else:
        entry = rbac_models.ConfigEntry(config_key=key, config_value=value)
        session.add(entry)
    session.commit()


def list_users(session: Session) -> list[dict[str, Any]]:
    users = session.execute(select(rbac_models.User).order_by(rbac_models.User.id)).scalars().all()
    results: list[dict[str, Any]] = []
    for user in users:
        roles = [role.name for role in user.roles]
        results.append(
            {
                "id": user.id,
                "username": user.username,
                "roles": roles,
                "is_active": user.is_active,
                "is_superuser": user.is_superuser,
                "created_at": user.created_at.isoformat() if user.created_at else None,
            }
        )
    return results


def list_roles(session: Session) -> list[dict[str, Any]]:
    roles = session.execute(select(rbac_models.Role).order_by(rbac_models.Role.id)).scalars().all()
    return [
        {
            "id": role.id,
            "name": role.name,
            "description": role.description,
            "created_at": role.created_at.isoformat() if role.created_at else None,
        }
        for role in roles
    ]


def list_policies(session: Session) -> list[dict[str, Any]]:
    rules = (
        session.execute(select(rbac_models.CasbinRule).order_by(rbac_models.CasbinRule.id))
        .scalars()
        .all()
    )
    return [
        {
            "id": rule.id,
            "ptype": rule.ptype,
            "v0": rule.v0,
            "v1": rule.v1,
            "v2": rule.v2,
            "v3": rule.v3,
            "v4": rule.v4,
            "v5": rule.v5,
        }
        for rule in rules
    ]


def _get_or_create_role(session: Session, name: str) -> rbac_models.Role:
    role = session.execute(
        select(rbac_models.Role).where(rbac_models.Role.name == name)
    ).scalar_one_or_none()
    if role:
        return role
    role = rbac_models.Role(name=name, description="")
    session.add(role)
    session.flush()
    return role


def create_user(
    session: Session,
    username: str,
    password: str,
    roles: list[str],
    is_active: bool,
    is_superuser: bool,
) -> dict[str, Any]:
    existing = session.execute(
        select(rbac_models.User).where(rbac_models.User.username == username)
    ).scalar_one_or_none()
    if existing:
        raise ValueError("用户名已存在")
    salt = secrets.token_hex(16)
    password_hash = _hash_password(password, salt)
    user = rbac_models.User(
        username=username,
        password_hash=password_hash,
        password_salt=salt,
        is_active=is_active,
        is_superuser=is_superuser,
    )
    session.add(user)
    session.flush()
    for role_name in roles:
        role = _get_or_create_role(session, role_name)
        session.add(rbac_models.UserRole(user_id=user.id, role_id=role.id))
    session.commit()
    return {
        "id": user.id,
        "username": user.username,
        "roles": roles,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def update_user(
    session: Session,
    user_id: int,
    username: str | None,
    password: str | None,
    roles: list[str] | None,
    is_active: bool | None,
    is_superuser: bool | None,
) -> dict[str, Any]:
    user = session.get(rbac_models.User, user_id)
    if not user:
        raise ValueError("用户不存在")
    if username and username != user.username:
        existing = session.execute(
            select(rbac_models.User).where(rbac_models.User.username == username)
        ).scalar_one_or_none()
        if existing:
            raise ValueError("用户名已存在")
        user.username = username
    if password:
        salt = secrets.token_hex(16)
        user.password_salt = salt
        user.password_hash = _hash_password(password, salt)
    if is_active is not None:
        user.is_active = is_active
    if is_superuser is not None:
        user.is_superuser = is_superuser
    if roles is not None:
        session.query(rbac_models.UserRole).filter_by(user_id=user.id).delete()
        for role_name in roles:
            role = _get_or_create_role(session, role_name)
            session.add(rbac_models.UserRole(user_id=user.id, role_id=role.id))
    session.commit()
    return {
        "id": user.id,
        "username": user.username,
        "roles": [role.name for role in user.roles],
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def delete_user(session: Session, user_id: int) -> None:
    user = session.get(rbac_models.User, user_id)
    if not user:
        return
    session.query(rbac_models.UserRole).filter_by(user_id=user.id).delete()
    session.delete(user)
    session.commit()


def create_role(session: Session, name: str, description: str | None) -> dict[str, Any]:
    existing = session.execute(
        select(rbac_models.Role).where(rbac_models.Role.name == name)
    ).scalar_one_or_none()
    if existing:
        raise ValueError("角色已存在")
    role = rbac_models.Role(name=name, description=description or "")
    session.add(role)
    session.commit()
    return {
        "id": role.id,
        "name": role.name,
        "description": role.description,
        "created_at": role.created_at.isoformat() if role.created_at else None,
    }


def update_role(
    session: Session, role_id: int, name: str | None, description: str | None
) -> dict[str, Any]:
    role = session.get(rbac_models.Role, role_id)
    if not role:
        raise ValueError("角色不存在")
    if name and name != role.name:
        existing = session.execute(
            select(rbac_models.Role).where(rbac_models.Role.name == name)
        ).scalar_one_or_none()
        if existing:
            raise ValueError("角色已存在")
        role.name = name
    if description is not None:
        role.description = description
    session.commit()
    return {
        "id": role.id,
        "name": role.name,
        "description": role.description,
        "created_at": role.created_at.isoformat() if role.created_at else None,
    }


def delete_role(session: Session, role_id: int) -> None:
    role = session.get(rbac_models.Role, role_id)
    if not role:
        return
    session.query(rbac_models.UserRole).filter_by(role_id=role.id).delete()
    session.delete(role)
    session.commit()


def create_policy(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    rule = rbac_models.CasbinRule(
        ptype=payload.get("ptype") or "p",
        v0=payload.get("v0"),
        v1=payload.get("v1"),
        v2=payload.get("v2"),
        v3=payload.get("v3"),
        v4=payload.get("v4"),
        v5=payload.get("v5"),
    )
    session.add(rule)
    session.commit()
    return {
        "id": rule.id,
        "ptype": rule.ptype,
        "v0": rule.v0,
        "v1": rule.v1,
        "v2": rule.v2,
        "v3": rule.v3,
        "v4": rule.v4,
        "v5": rule.v5,
    }


def update_policy(session: Session, rule_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    rule = session.get(rbac_models.CasbinRule, rule_id)
    if not rule:
        raise ValueError("策略不存在")
    for field in ("ptype", "v0", "v1", "v2", "v3", "v4", "v5"):
        if field in payload:
            setattr(rule, field, payload.get(field))
    session.commit()
    return {
        "id": rule.id,
        "ptype": rule.ptype,
        "v0": rule.v0,
        "v1": rule.v1,
        "v2": rule.v2,
        "v3": rule.v3,
        "v4": rule.v4,
        "v5": rule.v5,
    }


def delete_policy(session: Session, rule_id: int) -> None:
    rule = session.get(rbac_models.CasbinRule, rule_id)
    if not rule:
        return
    session.delete(rule)
    session.commit()
