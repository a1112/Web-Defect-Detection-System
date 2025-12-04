# coding: utf-8
from sqlalchemy import Column, DateTime, Integer, SmallInteger, text
from sqlalchemy.dialects.mysql import TINYINT, VARCHAR
from sqlalchemy.orm import declarative_base

Base = declarative_base()
metadata = Base.metadata


class Defectbyclass(Base):
    __tablename__ = 'defectbyclass'

    ID = Column(Integer, primary_key=True)
    SeqNo = Column(Integer, index=True)
    allclass = Column(Integer, server_default=text("'0'"))
    class0 = Column(Integer, server_default=text("'0'"))
    class1 = Column(Integer, server_default=text("'0'"))
    class2 = Column(Integer, server_default=text("'0'"))
    class3 = Column(Integer, server_default=text("'0'"))
    class4 = Column(Integer, server_default=text("'0'"))
    class5 = Column(Integer, server_default=text("'0'"))
    class6 = Column(Integer, server_default=text("'0'"))
    class7 = Column(Integer, server_default=text("'0'"))
    class8 = Column(Integer, server_default=text("'0'"))
    class9 = Column(Integer, server_default=text("'0'"))
    class10 = Column(Integer, server_default=text("'0'"))
    class11 = Column(Integer, server_default=text("'0'"))
    class12 = Column(Integer, server_default=text("'0'"))
    class13 = Column(Integer, server_default=text("'0'"))
    class14 = Column(Integer, server_default=text("'0'"))
    class15 = Column(Integer, server_default=text("'0'"))
    class16 = Column(Integer, server_default=text("'0'"))
    class17 = Column(Integer, server_default=text("'0'"))
    class18 = Column(Integer, server_default=text("'0'"))
    class19 = Column(Integer, server_default=text("'0'"))
    class20 = Column(Integer, server_default=text("'0'"))
    class21 = Column(Integer, server_default=text("'0'"))
    class22 = Column(Integer, server_default=text("'0'"))
    class23 = Column(Integer, server_default=text("'0'"))
    class24 = Column(Integer, server_default=text("'0'"))
    class25 = Column(Integer, server_default=text("'0'"))
    class26 = Column(Integer, server_default=text("'0'"))
    class27 = Column(Integer, server_default=text("'0'"))
    class28 = Column(Integer, server_default=text("'0'"))
    class29 = Column(Integer, server_default=text("'0'"))
    class30 = Column(Integer, server_default=text("'0'"))
    class31 = Column(Integer, server_default=text("'0'"))


class Rcvsteelprop(Base):
    __tablename__ = 'rcvsteelprop'

    id = Column("ID",Integer, primary_key=True)
    steelID = Column("SteelID",VARCHAR(64))
    steelType = Column("SteelType",VARCHAR(32))
    width = Column("Width",Integer)
    thick = Column("Thick",Integer)
    len = Column("Len",Integer)
    addTime = Column("AddTime",DateTime)
    used = Column("Used",Integer)


class Steelrecord(Base):
    __tablename__ = 'steelrecord'
    id = Column("ID",Integer, primary_key=True)
    seqNo = Column("SeqNo",Integer, nullable=False)
    steelID = Column("SteelID",VARCHAR(64), index=True)
    steelType = Column("SteelType",VARCHAR(32))
    steelLen = Column("SteelLen",Integer)
    width = Column("Width",Integer)
    thick = Column("Thick",SmallInteger)
    defectNum = Column("DefectNum",SmallInteger)
    detectTime = Column("DetectTime",DateTime)
    grade = Column("Grade",TINYINT)
    warn = Column("warn",TINYINT)
    steelOut = Column(TINYINT)
    cycle = Column(TINYINT)
    client = Column(VARCHAR(64))


class Steelwidth(Base):
    __tablename__ = 'steelwidth'

    id = Column(Integer, primary_key=True)
    seqNo = Column(Integer, nullable=False, index=True)
    len = Column(Integer)
    width = Column(Integer)


class Userclass(Base):
    __tablename__ = 'userclass'

    ID = Column(Integer, primary_key=True)
    ClassID = Column(SmallInteger, nullable=False)
    StartTime = Column(Integer)
    EndTime = Column(Integer)
    Name = Column(VARCHAR(32))
    ClassDesc = Column(VARCHAR(128))


class Userinfo(Base):
    __tablename__ = 'userinfo'

    ID = Column(Integer, primary_key=True)
    UserID = Column(SmallInteger, nullable=False)
    ClassID = Column(TINYINT)
    GroupID = Column(TINYINT)
    Name = Column(VARCHAR(32))
    Passwd = Column(VARCHAR(32))
    UserDesc = Column(VARCHAR(128))
