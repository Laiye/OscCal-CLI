ITEM_CONFIGS = {
    "amp": {
        "title": "ΔV(幅度) 校准结果",
        "columns": ["序号", "通道", "挡位(V/div)", "标准值(V)", "被校示值(V)", "相对误差(%)"],
        "error_col": 5,
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
    },
    "delta_time": {
        "title": "Δt(时间) 校准结果",
        "columns": ["序号", "通道", "挡位(s/div)", "标准值MT(s)", "被校示值tm(s)", "相对误差(%)"],
        "error_col": 5,
    },
    "bandwidth": {
        "title": "频带宽度 校准结果",
        "columns": ["序号", "通道", "挡位(V/div)", "实测值(MHz)"],
        "error_col": None,
        "min_col": 3,
    },
    "transient": {
        "title": "上升时间及过冲 校准结果",
        "columns": ["通道", "上升时间(ns)", "过冲(%)", "探头上升时间(ps)"],
        "error_col": None,
    },
}

EXCEL_ITEM_CONFIGS = {
    "amp": {
        "title": "幅度(ΔV)",
        "headers": ["序号", "通道", "挡位(V/div)", "标准值(V)", "被校示值(V)", "相对误差(%)"],
        "error_col": 5,
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
    },
    "delta_time": {
        "title": "Δt(时间)",
        "headers": ["序号", "通道", "挡位(s/div)", "标准值MT(s)", "被校示值tm(s)", "相对误差(%)"],
        "error_col": 5,
    },
    "bandwidth": {
        "title": "频带宽度",
        "headers": ["序号", "通道", "挡位(V/div)", "实测值(MHz)"],
        "error_col": None,
        "min_col": 3,
    },
    "transient": {
        "title": "上升时间及过冲",
        "headers": ["通道", "上升时间(ns)", "过冲(%)", "探头上升时间(ps)"],
        "error_col": None,
    },
}
