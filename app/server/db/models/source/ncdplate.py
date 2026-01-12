# coding: utf-8
from sqlalchemy import Column, DateTime, Integer, SmallInteger, text
from sqlalchemy.dialects.mysql import TINYINT, VARCHAR
from sqlalchemy.orm import declarative_base

Base = declarative_base()
metadata = Base.metadata


class Rcvsteelprop(Base):
    """接收钢板订单/来料属性信息，对应原始钢板规格。"""

    __tablename__ = 'rcvsteelprop'

    id = Column("ID", Integer, primary_key=True, comment="主键 ID")
    steelID = Column("SteelID", VARCHAR(64), comment="钢板号/卷号")
    steelType = Column("SteelType", VARCHAR(32), comment="钢种")
    width = Column("Width", Integer, comment="钢板宽度（mm）")
    thick = Column("Thick", Integer, comment="钢板厚度（mm）")
    len = Column("Len", Integer, comment="钢板长度（mm）")
    addTime = Column("AddTime", DateTime, comment="记录创建时间")
    used = Column("Used", Integer, comment="是否已使用标记")


class Steelrecord(Base):
    """钢板检测结果主表，一卷（序列号）一条记录。"""

    __tablename__ = 'steelrecord'

    id = Column("ID", Integer, primary_key=True, comment="主键 ID")
    seqNo = Column("SeqNo", Integer, nullable=False, comment="钢板序列号（流水号）")
    steelID = Column("SteelID", VARCHAR(64), index=True, comment="钢板号/卷号")
    steelType = Column("SteelType", VARCHAR(32), comment="钢种")
    steelLen = Column("SteelLen", Integer, comment="实测长度（mm）")
    width = Column("Width", Integer, comment="实测宽度（mm）")
    thick = Column("Thick", SmallInteger, comment="实测厚度（mm）")
    defectNum = Column("DefectNum", SmallInteger, comment="缺陷总数")
    detectTime = Column("DetectTime", DateTime, comment="检测时间")
    grade = Column("Grade", TINYINT, comment="钢板质量等级（数字）")
    warn = Column("warn", TINYINT, comment="预警标记")
    steelOut = Column(TINYINT, comment="是否出库标记")
    cycle = Column(TINYINT, comment="机组机架/周期等附加信息")
    client = Column(VARCHAR(64), comment="客户名称")


class Steelwidth(Base):
    """钢板宽度/长度采样信息，用于更精细的尺寸分析。"""

    __tablename__ = 'steelwidth'

    id = Column(Integer, primary_key=True, comment="主键 ID")
    seqNo = Column(Integer, nullable=False, index=True, comment="钢板序列号（流水号）")
    len = Column(Integer, comment="该采样段长度（mm）")
    width = Column(Integer, comment="该采样段宽度（mm）")
