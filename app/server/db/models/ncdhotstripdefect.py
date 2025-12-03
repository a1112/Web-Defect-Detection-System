# coding: utf-8
from sqlalchemy import Column, Integer, text
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()
metadata = Base.metadata


class Camdefect1(Base):
    __tablename__ = 'camdefect1'

    id = Column(Integer, primary_key=True)
    defectID = Column(Integer, nullable=False)
    camNo = Column(Integer)
    seqNo = Column(Integer, nullable=False, index=True)
    imgIndex = Column(Integer)
    defectClass = Column(Integer)
    leftInImg = Column(Integer)
    rightInImg = Column(Integer)
    topInImg = Column(Integer)
    bottomInImg = Column(Integer)
    leftInSrcImg = Column(Integer)
    rightInSrcImg = Column(Integer)
    topInSrcImg = Column(Integer)
    bottomInSrcImg = Column(Integer)
    leftInObj = Column(Integer)
    rightInObj = Column(Integer)
    topInObj = Column(Integer)
    bottomInObj = Column(Integer)
    grade = Column(TINYINT)
    area = Column(Integer)
    leftToEdge = Column(Integer)
    rightToEdge = Column(Integer)
    cycle = Column(Integer, server_default=text("'0'"))


class Camdefect2(Base):
    __tablename__ = 'camdefect2'

    id = Column(Integer, primary_key=True)
    defectID = Column(Integer, nullable=False)
    camNo = Column(Integer)
    seqNo = Column(Integer, nullable=False, index=True)
    imgIndex = Column(Integer)
    defectClass = Column(Integer)
    leftInImg = Column(Integer)
    rightInImg = Column(Integer)
    topInImg = Column(Integer)
    bottomInImg = Column(Integer)
    leftInSrcImg = Column(Integer)
    rightInSrcImg = Column(Integer)
    topInSrcImg = Column(Integer)
    bottomInSrcImg = Column(Integer)
    leftInObj = Column(Integer)
    rightInObj = Column(Integer)
    topInObj = Column(Integer)
    bottomInObj = Column(Integer)
    grade = Column(TINYINT)
    area = Column(Integer)
    leftToEdge = Column(Integer)
    rightToEdge = Column(Integer)
    cycle = Column(Integer, server_default=text("'0'"))


class Camdefectsum1(Base):
    __tablename__ = 'camdefectsum1'

    id = Column(Integer, primary_key=True)
    seqNo = Column(Integer, nullable=False, index=True)
    defectClass = Column(Integer)
    defectNum = Column(Integer)
    defectArea = Column(Integer)


class Camdefectsum2(Base):
    __tablename__ = 'camdefectsum2'

    id = Column(Integer, primary_key=True)
    seqNo = Column(Integer, nullable=False, index=True)
    defectClass = Column(Integer)
    defectNum = Column(Integer)
    defectArea = Column(Integer)


class Tempdefect1(Base):
    __tablename__ = 'tempdefect1'

    id = Column(Integer, primary_key=True)
    camNo = Column(Integer)
    seqNo = Column(Integer, nullable=False, index=True)
    imgIndex = Column(Integer)
    defectClass = Column(Integer)
    leftInImg = Column(Integer)
    rightInImg = Column(Integer)
    topInImg = Column(Integer)
    bottomInImg = Column(Integer)
    grade = Column(TINYINT)
    vendor = Column(TINYINT)


class Tempdefect2(Base):
    __tablename__ = 'tempdefect2'

    id = Column(Integer, primary_key=True)
    camNo = Column(Integer)
    seqNo = Column(Integer, nullable=False, index=True)
    imgIndex = Column(Integer)
    defectClass = Column(Integer)
    leftInImg = Column(Integer)
    rightInImg = Column(Integer)
    topInImg = Column(Integer)
    bottomInImg = Column(Integer)
    grade = Column(TINYINT)
    vendor = Column(TINYINT)
