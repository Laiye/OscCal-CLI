"""校准项目注册：项目键、规范条款与执行顺序。

v0.2.0 起按 JJF 1057-2026 第 7 章重建项目集，旧项目（amp、旧法 dc_gain、
delta_time、旧法 bandwidth、transient）已全部删除，**不保留别名与回退路径**。

本模块只描述元数据与顺序，不 import 具体实现：各项目实现完成后把类注册进
`RUNNERS`（M3'~M5' 逐个填充），避免重建期出现循环导入。
"""

CALIBRATION_ITEMS = [
    {"name": "input_impedance", "clause": "7.3", "title": "输入阻抗"},
    {"name": "dc_gain", "clause": "7.4", "title": "直流增益"},
    {"name": "dc_offset", "clause": "7.5", "title": "直流偏置"},
    {"name": "freq_response_bandwidth", "clause": "7.6", "title": "频率响应、频带宽度"},
    {"name": "enob", "clause": "7.7", "title": "动态有效位数"},
    {"name": "rise_time", "clause": "7.8", "title": "上升时间"},
    {"name": "timebase_error", "clause": "7.9", "title": "时基（采集速率）误差"},
    {"name": "delta_v", "clause": "7.11", "title": "ΔV（幅度）测量"},
    {"name": "delta_t", "clause": "7.12", "title": "Δt（时间）测量"},
    {"name": "random_noise", "clause": "7.13", "title": "随机噪声"},
]

ITEM_ORDER = [item["name"] for item in CALIBRATION_ITEMS]

ITEM_BY_NAME = {item["name"]: item for item in CALIBRATION_ITEMS}

# 项目名 -> runner（可调用对象）。重建期为空，随 M3'~M5' 填充。
RUNNERS: dict = {}
