# 创建服务

server/ 目录 为服务端，使用fastapi,通过读取配置文件（json）来设置 bkjc_database 的连接，以及 图像数据目录
现在以访问 ncdplate ,ncdplatedefect 为例，
    Rcvsteelprop : 二级信息表 （甲方发送的数据）   
    Steelrecord：钢板记录表 steelID为Rcvsteelprop.steelID   seqNo 为核心字段
    Camdefect1：上表面缺陷数据表 seqNo字段为 Steelrecord.seqNo
    Camdefect2： 下表面缺陷数据表 seqNo字段为 Steelrecord.seqNo

数据文件：
    \\127.0.0.1\imgsrc1 为上表面图像文件保存位置
    \\127.0.0.1\imgsrc2 为下表面图像文件保存位置

api 内容 不要直接访问数据库，通过修改优化 bkjc_database 完成，api 中不包含数据库的直接表名称，
    bkjc_database 可以再使用一层model返回，不直接返回数据库对象，目前以 ncdplate数据库为主，不需要考虑3.0数据库
        
    1： 获取N 条 Steelrecord 记录
    2： 对 Steelrecord 的 时间查询
    3： 对 Steelrecord 的 板号查询
    4： 对 Steelrecord的 ID 查询，
    4： 对 Camdefect 的 seqNo 查询 （指定表面 全部，上表面，下表面 （0，1，2）） 附带缺陷统计
    5： 图像查询 suface,seqNo,imageIndex 例如拼接为 \\127.0.0.1\imgsrc1\7\2D\1.jpg 返回 ，
        可指定横向纵向尺寸进行压缩，只指定其中之一为 比例压缩，都不指定为原图
    6:通过 表面 缺陷id 的裁剪图像返回，topInImg...为缺陷位于图像上的位置， 
    7：通过详细信息的缺陷返回（suface,seqNo,imageIndex，x,y,w,h）
        6,7 增加可选参数 如 边界拓展
    8：增加单个表面的完整拼接图像返回， 增加一些可选参数
    9：瓦片加载相关api,根据完整拼接的图像

    注意图像数据的缓存方法，避免频繁IO。

编写 demo 测试功能


    
    