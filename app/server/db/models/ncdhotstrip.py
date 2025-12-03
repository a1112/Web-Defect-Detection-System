# coding: utf-8
from sqlalchemy import Column, DateTime, Index, Integer, SmallInteger, text
from sqlalchemy.dialects.mysql import TINYINT, VARCHAR
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()
metadata = Base.metadata


class Defectbyclass(Base):
    __tablename__ = 'defectbyclass'
    __table_args__ = (
        Index('seqNo', 'seqNo', 'classNo'),
    )

    id = Column(Integer, primary_key=True)
    seqNo = Column(Integer)
    classNo = Column(Integer, server_default=text("'0'"))
    defectNum = Column(Integer, server_default=text("'0'"))
    numOnSurface0 = Column(Integer, server_default=text("'0'"))
    numOnSurface1 = Column(Integer, server_default=text("'0'"))


class Rcvsteelprop(Base):
    __tablename__ = 'rcvsteelprop'

    id = Column(Integer, primary_key=True)
    steelID = Column(VARCHAR(64))
    steelType = Column(VARCHAR(32))
    width = Column(Integer)
    thick = Column(Integer)
    len = Column(Integer)
    client = Column(VARCHAR(64))
    hard = Column(Integer)
    addTime = Column(DateTime)
    used = Column(Integer)


class Steelrecord(Base):
    __tablename__ = 'steelrecord'

    id = Column(Integer, primary_key=True)
    seqNo = Column(Integer, nullable=False)
    steelID = Column(VARCHAR(64), index=True)
    steelType = Column(VARCHAR(32))
    steelLen = Column(Integer)
    width = Column(Integer)
    thick = Column(SmallInteger)
    defectNum = Column(SmallInteger)
    detectTime = Column(DateTime)
    grade = Column(TINYINT)
    warn = Column(TINYINT)
    steelOut = Column(TINYINT)
    client = Column(VARCHAR(64))
    hard = Column(Integer)
    cycle = Column(Integer)


class Steelwarn(Base):
    __tablename__ = 'steelwarn'
    __table_args__ = (
        Index('seqNo', 'seqNo', 'surface', 'defectClass'),
    )

    id = Column(Integer, primary_key=True)
    seqNo = Column(Integer, nullable=False)
    surface = Column(Integer)
    defectClass = Column(Integer)
    classTitle = Column(VARCHAR(32))
    defectNum = Column(Integer)
    defectArea = Column(Integer)
    startLen = Column(Integer)
    endLen = Column(Integer)
    processed = Column(TINYINT)


class Steelwidth(Base):
    __tablename__ = 'steelwidth'

    id = Column(Integer, primary_key=True)
    seqNo = Column(Integer, nullable=False, index=True)
    len = Column(Integer)
    width = Column(Integer)


class Userinfo(Base):
    __tablename__ = 'userinfo'

    id = Column(Integer, primary_key=True)
    userID = Column(SmallInteger, nullable=False)
    classID = Column(TINYINT)
    groupID = Column(TINYINT)
    name = Column(VARCHAR(32))
    passwd = Column(VARCHAR(32))
    userDesc = Column(VARCHAR(128))
