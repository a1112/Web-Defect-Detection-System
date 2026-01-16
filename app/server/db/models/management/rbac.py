# coding: utf-8
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()
metadata = Base.metadata


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), nullable=False, unique=True, index=True)
    password_hash = Column(String(256), nullable=False)
    password_salt = Column(String(64), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    is_superuser = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=datetime.utcnow)

    roles = relationship("Role", secondary="user_roles", back_populates="users")


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False, unique=True)
    description = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    users = relationship("User", secondary="user_roles", back_populates="roles")


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_user_role"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)


class CasbinRule(Base):
    __tablename__ = "casbin_rule"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ptype = Column(String(255), nullable=False)
    v0 = Column(String(255), nullable=True)
    v1 = Column(String(255), nullable=True)
    v2 = Column(String(255), nullable=True)
    v3 = Column(String(255), nullable=True)
    v4 = Column(String(255), nullable=True)
    v5 = Column(String(255), nullable=True)


class ConfigEntry(Base):
    __tablename__ = "config_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    config_key = Column(String(128), nullable=False, unique=True, index=True)
    config_value = Column(Text, nullable=False)
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=datetime.utcnow)


class CacheRecord(Base):
    """
    缓存记录表：记录每块钢板在磁盘缓存中的元数据（对应 cache.json），
    通过产线 key、流水号作为主查询依据。
    """

    __tablename__ = "cache_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    line_key = Column(String(64), nullable=False, index=True, comment="产线 key（对应 DEFECT_LINE_KEY 或映射表配置）")
    seq_no = Column(Integer, nullable=False, index=True, comment="钢板流水号 SeqNo")
    surface = Column(String(16), nullable=False, comment="表面：top/bottom")
    view = Column(String(32), nullable=False, comment="视角模式：2D 等")
    tile_max_level = Column(Integer, nullable=True, comment="瓦片缓存最大层级（cache.json.tile.max_level）")
    tile_size = Column(Integer, nullable=True, comment="瓦片基准尺寸（cache.json.tile.tile_size）")
    defect_expand = Column(Integer, nullable=True, comment="缺陷缓存扩展像素（cache.json.defects.expand）")
    defect_cache_enabled = Column(Boolean, nullable=False, default=True, comment="是否启用缺陷缓存")
    disk_cache_enabled = Column(Boolean, nullable=False, default=True, comment="是否启用磁盘缓存")
    meta_json = Column(Text, nullable=True, comment="原始 cache.json 内容快照（JSON 文本）")
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=datetime.utcnow)


class DefectStat(Base):
    """
    缺陷统计表：按产线 key + 流水号 + 缺陷名称 聚合数量，
    方便传统仪表盘快速拉取统计信息。
    """

    __tablename__ = "defect_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    line_key = Column(String(64), nullable=False, index=True, comment="产线 key")
    seq_no = Column(Integer, nullable=False, index=True, comment="钢板流水号 SeqNo")
    surface = Column(String(16), nullable=True, comment="表面：top/bottom，可为空表示整板统计")
    defect_name = Column(String(64), nullable=False, comment="缺陷名称/类别显示名称")
    defect_class = Column(Integer, nullable=True, comment="缺陷类别编号（camdefect 表中的 defectClass）")
    count = Column(Integer, nullable=False, default=0, comment="缺陷数量")
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=datetime.utcnow)


class SteelGrade(Base):
    """
    钢板判级表：按产线 key + 流水号记录钢板综合质量等级及标记信息。
    """

    __tablename__ = "steel_grades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    line_key = Column(String(64), nullable=False, index=True, comment="产线 key")
    seq_no = Column(Integer, nullable=False, index=True, comment="钢板流水号 SeqNo")
    steel_id = Column(String(64), nullable=True, comment="钢板号/卷号")
    grade = Column(String(32), nullable=True, comment="钢板等级（如 A/B/C，或自定义编码）")
    grade_code = Column(Integer, nullable=True, comment="钢板等级数字编码（与 steelrecord.Grade 可关联）")
    mark_flag = Column(Boolean, nullable=False, default=False, comment="是否存在人工标记")
    mark_reason = Column(Text, nullable=True, comment="标记原因/备注")
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=datetime.utcnow)


class DefectGrade(Base):
    """
    缺陷判级表：按缺陷 ID 记录判级与标记信息。
    """

    __tablename__ = "defect_grades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    line_key = Column(String(64), nullable=False, index=True, comment="产线 key")
    seq_no = Column(Integer, nullable=False, index=True, comment="钢板流水号 SeqNo")
    surface = Column(String(16), nullable=False, comment="表面：top/bottom")
    defect_id = Column(Integer, nullable=False, index=True, comment="缺陷 ID（对应 camdefect 表 defectID）")
    defect_class = Column(Integer, nullable=True, comment="缺陷类别编号")
    grade = Column(String(32), nullable=True, comment="缺陷等级（如 A/B/C，或自定义编码）")
    grade_code = Column(Integer, nullable=True, comment="缺陷等级数字编码")
    mark_flag = Column(Boolean, nullable=False, default=False, comment="是否存在人工标记")
    mark_reason = Column(Text, nullable=True, comment="标记原因/备注")
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=datetime.utcnow)
