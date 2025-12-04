# coding: utf-8
from sqlalchemy import Column, DateTime, Float, Integer
from sqlalchemy.dialects.mysql import DATETIME, TINYINT, VARCHAR
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()
metadata = Base.metadata


class Camera(Base):
    __tablename__ = 'camera'

    ID = Column(Integer, primary_key=True)
    cam = Column(TINYINT)
    SeqNo = Column(Integer)
    Temper = Column(TINYINT)
    FrameRate = Column(Float)
    AverGray = Column(Float)
    Exptime = Column(Integer)
    AddTime = Column(DateTime)


class Cooler(Base):
    __tablename__ = 'cooler'

    ID = Column(Integer, primary_key=True)
    CoolerNo = Column(TINYINT)
    Temper = Column(TINYINT)
    Intense = Column(TINYINT)
    AddTime = Column(DateTime)


class Disk(Base):
    __tablename__ = 'disk'

    ID = Column(Integer, primary_key=True)
    name = Column(VARCHAR(16), index=True)
    total = Column(Float)
    free = Column(Float)
    addTime = Column(DateTime)


class Light(Base):
    __tablename__ = 'light'

    ID = Column(Integer, primary_key=True)
    LightNo = Column(TINYINT)
    Temper = Column(TINYINT)
    Intense = Column(TINYINT)
    AddTime = Column(DateTime)


class Net(Base):
    __tablename__ = 'net'

    ID = Column(Integer, primary_key=True)
    ip = Column(VARCHAR(32), index=True)
    online = Column(TINYINT)
    up = Column(Float)
    down = Column(Float)
    addTime = Column(DateTime)


class Report(Base):
    __tablename__ = 'report'

    ID = Column(Integer, primary_key=True)
    sender = Column(VARCHAR(32))
    type = Column(TINYINT)
    code = Column(TINYINT)
    info = Column(VARCHAR(256))
    time = Column(DATETIME(fsp=6))


class Rkmonitor(Base):
    __tablename__ = 'rkmonitor'

    ID = Column(Integer, primary_key=True)
    DateTime = Column(DateTime)
    Temperature = Column(Float)
    Humidity = Column(Float)


class Tank(Base):
    __tablename__ = 'tank'

    ID = Column(Integer, primary_key=True)
    TankNo = Column(TINYINT)
    Temper = Column(TINYINT)
    Intense = Column(TINYINT)
    AddTime = Column(DateTime)
