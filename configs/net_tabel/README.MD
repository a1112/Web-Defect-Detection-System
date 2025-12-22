# 转发，代理规则文档
1： 不考虑安全问题 仅限内网


net_tabel 下为 数据的构建规则
    1，根据 socket.gethostname() 或许的 电脑名称在 configs/net_tabel/DATA 查找对应配置
    2，未匹配的·电脑使用 configs/net_tabel/DEFAULT 的 配置
    前端 的标题换成产线名称
    配置按照文件夹区分 ，访问 map.json 构建多进程数据服务。
    map.json 的编写需求：
        {
            ...
            :[{...},{...},{
                                产线名称，ip,服务端口，数据库名称,账号密码（因为基本是一样的，写到同文件默认）
                                转发方式：代理（代理的端口映射） / 直连（直连目标为什么设置的信息）   
                                ，启动的 fastapi 服务监听ip（默认 0.0.0.0），指定服务端口，暴露给Figmaaidefectdetectionsystem,数据库，文件夹 ip 替换
                                转发方式 代表 api 在 另外的电脑或者进程，给定代理 参数，也需要给 产线名称 ， 直理解多一些数据库，图像位置，一般在 server.json/server_small.json 的基础上替换 ip
                            }]
            ...
        }

server.json   server_small.json 依旧保留，参数配置的构建变成了：
    1： 扫描 socket.gethostname() 确定构建位置，以及构建方法
    2： 一级一级向上确定完整的配置文件 以 server.json/server_small.json作为基础模板，替换掉被重新设置的值以及最后的的format
             "\\\\{ip}\\imgsrc1".format(ip)
            "top_root": "\\\\127.0.0.1\\imgsrc1",更改为这种  "top_root": "\\\\{ip}\\imgsrc1",
    3，新建 Web-Defect-Detection-System/main_server.py 来构建脚本启动 的 生产环境

修改 vite.config.ts

增加一个统一管理 api 的 api，用于网络广播链路同步
前需要增加 /api_list 的请求访问到 全部的 数据节点列表
需要通过 cookie 来 记录 上次访问，避免每次刷新都要重新切换数据原

使用 生成以及运行 Nginx 文件 完成 转发，
客户端 切换产线使用到 /产线/api  -> 对应后端 /api

服务端： Web-Defect-Detection-System
前端 ： Figmaaidefectdetectionsystem


URL 允许中文 
使用 目前 Web-Defect-Detection-System/configs/net_tabel/DATA/WIN-QKKTQK5NMSK 中 文件夹 名称 作为 map.json 的 产线名称，
有一些信息在 Web-Defect-Detection-System/configs/net_tabel/DATA/WIN-QKKTQK5NMSK/core.py 中。