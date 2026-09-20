"""校准结果表格配置：终端（ITEM_CONFIGS）与 Excel（EXCEL_ITEM_CONFIGS）各一份。

两份配置的列顺序完全一致，`precision` 按列声明显示精度：
("sig", n) 保留 n 位有效数字（与校准过程终端表格同一规则），
("dec", n) 保留 n 位小数，None 表示原样输出（序号、通道、状态等文本列）。
Excel 导出与 `osccal show` 共用该规格，避免报告出现读数原始位数（如 15 位）而失真。
"""

# 各校准项目的显示精度，按列顺序排列
ITEM_PRECISION = {
    "amp": [None, None, ("dec", 3), ("sig", 3), ("sig", 3), ("dec", 2)],
    "dc_gain": [
        None,
        None,
        None,
        ("dec", 3),
        ("sig", 3),
        ("sig", 3),
        ("sig", 3),
        ("sig", 3),
        ("dec", 2),
    ],
    "delta_time": [None, None, ("sig", 4), ("sig", 4), ("sig", 4), ("dec", 2)],
    "bandwidth": [None, None, None, ("dec", 2), None],
    "transient": [None, ("sig", 2), ("sig", 2), ("dec", 0)],
}

ITEM_CONFIGS = {
    "amp": {
        "title": "ΔV(幅度) 校准结果",
        "columns": ["序号", "通道", "挡位(V/div)", "标准值(V)", "被校示值(V)", "相对误差(%)"],
        "error_col": 5,
        "precision": ITEM_PRECISION["amp"],
    },
    "dc_gain": {
        "title": "直流增益 校准结果",
        "columns": [
            "序号",
            "通道",
            "阻抗",
            "挡位(V/div)",
            "标准值U+(V)",
            "标准值U-(V)",
            "被校示值Ur+(V)",
            "被校示值Ur-(V)",
            "直流增益误差(%)",
        ],
        "error_col": 8,
        "precision": ITEM_PRECISION["dc_gain"],
    },
    "delta_time": {
        "title": "Δt(时间) 校准结果",
        "columns": ["序号", "通道", "挡位(s/div)", "标准值MT(s)", "被校示值tm(s)", "相对误差(%)"],
        "error_col": 5,
        "precision": ITEM_PRECISION["delta_time"],
    },
    "bandwidth": {
        "title": "频带宽度 校准结果",
        "columns": ["序号", "通道", "挡位(V/div)", "实测值(MHz)", "结果状态"],
        "error_col": None,
        "min_col": 3,
        "precision": ITEM_PRECISION["bandwidth"],
    },
    "transient": {
        "title": "上升时间及过冲 校准结果",
        "columns": ["通道", "上升时间(ns)", "过冲(%)", "探头上升时间(ps)"],
        "error_col": None,
        "precision": ITEM_PRECISION["transient"],
    },
}

EXCEL_ITEM_CONFIGS = {
    "amp": {
        "title": "幅度(ΔV)",
        "headers": ["序号", "通道", "挡位(V/div)", "标准值(V)", "被校示值(V)", "相对误差(%)"],
        "error_col": 5,
        "precision": ITEM_PRECISION["amp"],
    },
    "dc_gain": {
        "title": "直流增益",
        "headers": [
            "序号",
            "通道",
            "阻抗",
            "挡位(V/div)",
            "标准值U+(V)",
            "标准值U-(V)",
            "被校示值Ur+(V)",
            "被校示值Ur-(V)",
            "直流增益误差(%)",
        ],
        "error_col": 8,
        "precision": ITEM_PRECISION["dc_gain"],
    },
    "delta_time": {
        "title": "Δt(时间)",
        "headers": ["序号", "通道", "挡位(s/div)", "标准值MT(s)", "被校示值tm(s)", "相对误差(%)"],
        "error_col": 5,
        "precision": ITEM_PRECISION["delta_time"],
    },
    "bandwidth": {
        "title": "频带宽度",
        "headers": ["序号", "通道", "挡位(V/div)", "实测值(MHz)", "结果状态"],
        "error_col": None,
        "min_col": 3,
        "precision": ITEM_PRECISION["bandwidth"],
    },
    "transient": {
        "title": "上升时间及过冲",
        "headers": ["通道", "上升时间(ns)", "过冲(%)", "探头上升时间(ps)"],
        "error_col": None,
        "precision": ITEM_PRECISION["transient"],
    },
}
