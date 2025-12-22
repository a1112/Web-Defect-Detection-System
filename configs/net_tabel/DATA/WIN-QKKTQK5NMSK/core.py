from fastapi import FastAPI
from collections import defaultdict

basePrt=8200

tabelList = {
    "1": {
        "FactoryID": 1,
        "DeviceName": "热处理2号线",
        "ip": "172.25.2.10",
    },
    "2": {
        "FactoryID": 2,
        "DeviceName": "热处理4号线",
        "ip": "172.25.2.12",
    },
    "3": {
        "FactoryID": 3,
        "DeviceName": "热处理5号线",
        "ip":"172.25.2.26",

    },
    "4": {
        "FactoryID": 4,
        "DeviceName": "热处理6号线",
        "ip": "172.25.2.27"
    },
    "5": {
        "FactoryID": 5,
        "DeviceName": "SED线",
        "ip": "172.25.2.11"

    },
    "6": {
        "FactoryID": 6,
        "DeviceName": "横切1号线",
        "ip": "172.25.3.7"
    },
    "7": {
        "FactoryID": 7,
        "DeviceName": "矫直4号线",
        "ip":"172.25.2.11"
    },
    "8": {
        "FactoryID": 8,
        "DeviceName": "矫直6号线",
        "ip":"172.25.2.42"
    },
    "9": {
        "FactoryID": 9,
        "DeviceName": "矫直7号线",
        "ip":"172.25.2.43"
    },
    "10": {
        "FactoryID": 10,
        "DeviceName": "热处理12号线",
        "ip":"172.25.2.99"
    },
    "11": {
        "FactoryID": 11,
        "DeviceName": "热处理11号线",
        "ip":"172.25.2.98"
    },
    "12": {
        "FactoryID": 12,
        "DeviceName": "矫直11号线",
        "ip":"172.25.2.114"
    },
    "13": {
        "FactoryID": 13,
        "DeviceName": "矫直12号线",
        "ip":"172.25.2.122"
    },
    "14": {
        "FactoryID": 14,
        "DeviceName": "矫直13号线",
        "ip":"172.25.2.123"
    },
    "15": {
        "FactoryID": 15,
        "DeviceName": "横切3号线",
        "ip":"172.25.2.138"
    },
    "16": {
        "FactoryID": 16,
        "DeviceName": "矫直8号线",
        "ip": "172.25.2.82"
    },
    "17": {
        "FactoryID": 17,
        "DeviceName": "矫直9号线",
        "ip":"172.25.2.83"
    },
    "18": {
        "FactoryID": 18,
        "DeviceName": "热处理8号线",
        "ip":"172.25.2.58"
    },
    "19": {
        "FactoryID": 19,
        "DeviceName": "热处理10号线",
        "ip":"172.25.2.60"
    },
    "20": {
        "FactoryID": 20,
        "DeviceName": "热处理9号线",
        "ip":"172.25.2.59"
    },
    "21": {
        "FactoryID": 21,
        "DeviceName": "横切2号线",
        "ip": "172.25.3.110"
    },

}


class ForwarderServer:
    def __init__(self, ip, port):
        self.app = FastAPI()
        self.ip = ip
        self.port = port


default_forwarder_server_dict = defaultdict(lambda: ForwarderServer(None, None))


app = FastAPI()
