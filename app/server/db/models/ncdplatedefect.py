# coding: utf-8
from sqlalchemy import Column, Integer, text
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()
metadata = Base.metadata


class Camdefect1(Base):
    """上表面（top）缺陷明细表，对应相机1。"""

    __tablename__ = 'camdefect1'

    id = Column(Integer, primary_key=True, comment="主键 ID")
    defectID = Column(Integer, nullable=False, comment="缺陷 ID（同一钢板唯一）")
    camNo = Column(Integer, comment="相机编号")
    seqNo = Column(Integer, nullable=False, index=True, comment="钢板序列号（流水号）")
    imgIndex = Column(Integer, comment="所在帧图像索引，线扫相机")
    defectClass = Column(Integer, comment="缺陷类别编号")
    leftInImg = Column(Integer, comment="在当前帧图像中的左边界像素坐标")  # 弃用
    rightInImg = Column(Integer, comment="在当前帧图像中的右边界像素坐标") # 弃用
    topInImg = Column(Integer, comment="在当前帧图像中的上边界像素坐标")   # 弃用
    bottomInImg = Column(Integer, comment="在当前帧图像中的下边界像素坐标")# 弃用
    leftInSrcImg = Column(Integer, comment="在原始源图像中的左边界像素坐标")
    rightInSrcImg = Column(Integer, comment="在原始源图像中的右边界像素坐标")
    topInSrcImg = Column(Integer, comment="在原始源图像中的上边界像素坐标")
    bottomInSrcImg = Column(Integer, comment="在原始源图像中的下边界像素坐标")
    leftInObj = Column(Integer, comment="在物理坐标系中的左边界（沿宽度方向）")
    rightInObj = Column(Integer, comment="在物理坐标系中的右边界（沿宽度方向）")
    topInObj = Column(Integer, comment="在物理坐标系中的上边界（沿长度方向）")
    bottomInObj = Column(Integer, comment="在物理坐标系中的下边界（沿长度方向）")
    grade = Column(TINYINT, comment="缺陷等级/严重程度原始编码")
    area = Column(Integer, comment="缺陷面积像素数")
    leftToEdge = Column(Integer, comment="缺陷到左边缘的距离（像素）")
    rightToEdge = Column(Integer, comment="缺陷到右边缘的距离（像素）")
    cycle = Column(Integer, server_default=text("'0'"), comment="机组周期/机架信息")


class Camdefect2(Base):
    """下表面（bottom）缺陷明细表，对应相机2。"""

    __tablename__ = 'camdefect2'

    id = Column(Integer, primary_key=True, comment="主键 ID")
    defectID = Column(Integer, nullable=False, comment="缺陷 ID（同一钢板唯一）")
    camNo = Column(Integer, comment="相机编号")
    seqNo = Column(Integer, nullable=False, index=True, comment="钢板序列号（流水号）")
    imgIndex = Column(Integer, comment="所在帧图像索引")
    defectClass = Column(Integer, comment="缺陷类别编号")
    leftInImg = Column(Integer, comment="在当前帧图像中的左边界像素坐标")
    rightInImg = Column(Integer, comment="在当前帧图像中的右边界像素坐标")
    topInImg = Column(Integer, comment="在当前帧图像中的上边界像素坐标")
    bottomInImg = Column(Integer, comment="在当前帧图像中的下边界像素坐标")
    leftInSrcImg = Column(Integer, comment="在原始源图像中的左边界像素坐标")
    rightInSrcImg = Column(Integer, comment="在原始源图像中的右边界像素坐标")
    topInSrcImg = Column(Integer, comment="在原始源图像中的上边界像素坐标")
    bottomInSrcImg = Column(Integer, comment="在原始源图像中的下边界像素坐标")
    leftInObj = Column(Integer, comment="在物理坐标系中的左边界（沿宽度方向）")
    rightInObj = Column(Integer, comment="在物理坐标系中的右边界（沿宽度方向）")
    topInObj = Column(Integer, comment="在物理坐标系中的上边界（沿长度方向）")
    bottomInObj = Column(Integer, comment="在物理坐标系中的下边界（沿长度方向）")
    grade = Column(TINYINT, comment="缺陷等级/严重程度原始编码")
    area = Column(Integer, comment="缺陷面积像素数")
    leftToEdge = Column(Integer, comment="缺陷到左边缘的距离（像素）")
    rightToEdge = Column(Integer, comment="缺陷到右边缘的距离（像素）")
    cycle = Column(Integer, server_default=text("'0'"), comment="机组周期/机架信息")


class Camdefectsum1(Base):
    """上表面（top）缺陷统计表，按缺陷类别聚合数量。"""

    __tablename__ = 'camdefectsum1'

    id = Column(Integer, primary_key=True, comment="主键 ID")
    seqNo = Column(Integer, nullable=False, index=True, comment="钢板序列号（流水号）")
    defectClass = Column(Integer, comment="缺陷类别编号")
    defectNum = Column(Integer, comment="该类别缺陷数量")


class Camdefectsum2(Base):
    """下表面（bottom）缺陷统计表，按缺陷类别聚合数量。"""

    __tablename__ = 'camdefectsum2'

    id = Column(Integer, primary_key=True, comment="主键 ID")
    seqNo = Column(Integer, nullable=False, index=True, comment="钢板序列号（流水号）")
    defectClass = Column(Integer, comment="缺陷类别编号")
    defectNum = Column(Integer, comment="该类别缺陷数量")
