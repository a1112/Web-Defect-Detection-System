# coding: utf-8
from sqlalchemy import Column, DateTime, Integer, String, Text, func, JSON
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()
metadata = Base.metadata


class DefectAnnotation(Base):
    """缺陷标注表，用于记录人工/自动标注信息。"""

    __tablename__ = "defect_annotation"

    id = Column(Integer, primary_key=True, autoincrement=True)
    line_key = Column(String(64), nullable=False, index=True, comment="产线 key")
    seq_no = Column(Integer, nullable=False, index=True, comment="钢板流水号 SeqNo")
    surface = Column(String(16), nullable=False, comment="表面：top/bottom")
    view = Column(String(32), nullable=False, comment="视角模式：2D/small 等")

    user = Column(String(64), nullable=True, comment="用户")
    method = Column(String(16), nullable=False, comment="标注方式：manual/auto")

    left = Column(Integer, nullable=False, comment="像素坐标 left")
    top = Column(Integer, nullable=False, comment="像素坐标 top")
    right = Column(Integer, nullable=False, comment="像素坐标 right")
    bottom = Column(Integer, nullable=False, comment="像素坐标 bottom")

    class_id = Column(Integer, nullable=True, comment="类别 ID")
    class_name = Column(String(128), nullable=True, comment="类别名称")
    mark = Column(String(128), nullable=True, comment="缺陷标记")
    export_payload = Column(JSON, nullable=True, comment="导出记录 JSON")
    extra = Column(Text, nullable=True, comment="扩展信息")

    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        comment="最后修改时间",
    )
