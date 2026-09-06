"""3 Series MDO 指令集（tektronix_mdo3.json）单元测试。

覆盖维度：
1. JSON 合法性与顶层结构字段
2. 必需 actions / keywords 是否齐全（对照 measure 模块的实际调用契约）
3. 每个 action 的结构完整性（commands_num 与 commands 长度一致等）
4. args_num 与 measure 模块实际调用参数个数一致
5. assemble_cmd 组装出的 SCPI 字符串与 3 Series MDO Programmer Manual 一致
6. 关键助记符采用手册文档形式（FIFty/MEG、AMPlitude 等）
"""

import json

import pytest

from osccal.core.command import assemble_cmd

# ===========================================================================
# 1. 顶层结构与合法性
# ===========================================================================


class TestMdo3Structure:
    """指令集顶层字段校验。"""

    def test_json_is_valid(self, mdo3_commands_path):
        with open(mdo3_commands_path, encoding="utf-8") as f:
            json.load(f)

    def test_top_level_keys(self, mdo3_commands):
        for key in ("name", "description", "type", "series", "feature", "keyword", "actions"):
            assert key in mdo3_commands, f"缺少顶层字段: {key}"

    def test_name(self, mdo3_commands):
        assert mdo3_commands["name"] == "Tektronix_3SeriesMDO"

    def test_type_is_pyvisa(self, mdo3_commands):
        assert mdo3_commands["type"] == "pyvisa"

    def test_series_covers_mdo34_and_mdo32(self, mdo3_commands):
        series = mdo3_commands["series"]
        assert "MDO34" in series
        assert "MDO32" in series

    def test_description_mentions_models(self, mdo3_commands):
        desc = mdo3_commands["description"]
        assert "MDO34" in desc
        assert "MDO32" in desc

    def test_feature_merge_mode(self, mdo3_commands):
        feature = mdo3_commands["feature"]
        assert feature["meas"] == "merge"
        assert feature["return_value_index"] == 1
        assert feature["get_value"] == "Direct"


# ===========================================================================
# 2. 必需 actions（对照 measure 模块实际调用）
# ===========================================================================

# measure 模块实际调用 _write_osc/_query_osc/setup_* 时用到的 action 集合
REQUIRED_ACTIONS = {
    "preset",  # base.init_devices
    "set_channel",  # base.setup_channel
    "set_trigger_source",  # base.setup_channel / bandwidth
    "set_vertical_scale",  # amp/dc_gain/bandwidth/delta_time/transient
    "set_vertical_position",  # base._adjust_vertical_position / transient
    "set_horizontal_scale",  # amp/bandwidth/delta_time/transient
    "set_acquisition_mode",  # amp/dc_gain/bandwidth
    "set_number_of_acquisitions",  # amp/dc_gain/bandwidth
    "set_trigger_level",  # transient
    "set_meas_source",  # comm.scpi_setup_measurement (merge)
    "set_meas_type",  # comm.scpi_setup_measurement (merge)
    "get_value",  # comm.read_measurement (merge)
    "set_impedance",  # base.setup_impedance
    "set_acquire_stop_after",  # transient
}


class TestMdo3Actions:
    """actions 字段校验。"""

    def test_required_actions_exist(self, mdo3_commands):
        actions = mdo3_commands["actions"]
        missing = REQUIRED_ACTIONS - set(actions.keys())
        assert not missing, f"缺少必需 action: {missing}"

    @pytest.mark.parametrize("action_name", sorted(REQUIRED_ACTIONS))
    def test_action_structural_integrity(self, mdo3_commands, action_name):
        """每个 action 含必需字段且 commands_num 与 commands 长度一致。"""
        action = mdo3_commands["actions"][action_name]
        for key in ("name", "type", "commands_num", "args_num", "commands", "args"):
            assert key in action, f"{action_name} 缺少字段: {key}"
        assert action["commands_num"] == len(action["commands"]), (
            f"{action_name}: commands_num({action['commands_num']}) != len(commands)({len(action['commands'])})"
        )

    @pytest.mark.parametrize("action_name", sorted(REQUIRED_ACTIONS))
    def test_action_name_matches_key(self, mdo3_commands, action_name):
        action = mdo3_commands["actions"][action_name]
        assert action["name"] == action_name

    # args_num 必须与 measure 模块实际调用时传入的参数个数一致
    @pytest.mark.parametrize(
        "action_name,expected_argc",
        [
            ("preset", 0),
            ("initialize", 0),  # *CLS;*RST 不带参数
            ("set_channel", 2),
            ("set_vertical_scale", 2),
            ("set_vertical_position", 2),
            ("set_trigger_source", 1),
            ("set_trigger_level", 2),
            ("set_horizontal_scale", 1),
            ("set_acquisition_mode", 1),
            ("set_number_of_acquisitions", 1),
            ("set_meas_source", 1),
            ("set_impedance", 2),
            ("set_meas_type", 1),
            ("get_value", 0),
            ("set_meas_method", 1),
            ("set_acquire_state", 1),
            ("set_acquire_stop_after", 1),
        ],
    )
    def test_action_args_num_contract(self, mdo3_commands, action_name, expected_argc):
        """action 声明的 args_num 应与调用方传入的参数个数一致。"""
        actions = mdo3_commands["actions"]
        if action_name not in actions:
            pytest.skip(f"{action_name} 不在指令集中（可选 action）")
        assert actions[action_name]["args_num"] == expected_argc, (
            f"{action_name}: args_num={actions[action_name]['args_num']}, 期望 {expected_argc}"
        )


# ===========================================================================
# 3. 必需 keywords（对照 measure 模块实际引用）
# ===========================================================================

REQUIRED_KEYWORDS = {
    "imp_fif",  # base._setup_signal_impedance
    "imp_meg",  # base._setup_signal_impedance
    "acquisition_mode_average",  # amp/dc_gain/bandwidth
    "meas_amp",  # amp/bandwidth
    "meas_period",  # delta_time
    "meas_mean",  # dc_gain
    "meas_risetime",  # transient
    "meas_pos_overshoot",  # transient
    "meas_max",  # base._adjust_vertical_position
    "meas_min",  # base._adjust_vertical_position
    "acquire_stop_after_single",  # transient
}


class TestMdo3Keywords:
    """keyword 字段校验。"""

    def test_required_keywords_exist(self, mdo3_commands):
        keywords = mdo3_commands["keyword"]
        missing = REQUIRED_KEYWORDS - set(keywords.keys())
        assert not missing, f"缺少必需 keyword: {missing}"

    def test_impedance_keywords(self, mdo3_commands):
        kw = mdo3_commands["keyword"]
        # 手册 §CH<x>:TERmination {FIFty|MEG|<NR3>}
        assert kw["imp_fif"] == "FIFty"
        assert kw["imp_meg"] == "MEG"

    def test_acquisition_mode_keywords(self, mdo3_commands):
        kw = mdo3_commands["keyword"]
        # 手册 §ACQuire:MODe {SAMple|PEAKdetect|HIRes|AVErage|ENVelope}
        assert kw["acquisition_mode_sample"] == "SAMple"
        assert kw["acquisition_mode_average"] == "AVErage"
        assert kw["acquisition_mode_peak"] == "PEAKdetect"

    @pytest.mark.parametrize(
        "kw_key,expected",
        [
            ("meas_amp", "AMPlitude"),
            ("meas_period", "PERIod"),
            ("meas_risetime", "RISe"),
            ("meas_freq", "FREQuency"),
            ("meas_mean", "MEAN"),
            ("meas_pos_overshoot", "POVershoot"),
            ("meas_max", "MAXimum"),
            ("meas_min", "MINimum"),
        ],
    )
    def test_measurement_keywords_match_manual(self, mdo3_commands, kw_key, expected):
        """测量类型助记符采用手册文档形式。"""
        assert mdo3_commands["keyword"][kw_key] == expected

    def test_stop_after_keywords(self, mdo3_commands):
        kw = mdo3_commands["keyword"]
        # 手册 §ACQuire:STOPAfter {RUNSTop|SEQuence}
        assert kw["acquire_stop_after_single"] == "SEQuence"
        assert kw["acquire_stop_after_run_stop"] == "RUNSTop"


# ===========================================================================
# 4. SCPI 组装对照手册（参数化）
# ===========================================================================

# (action_name, args, expected_scpi) —— 全部对照 3 Series MDO Programmer Manual
SCPI_CASES = [
    # 复位
    ("preset", (), "FACtory"),
    ("initialize", (), "*CLS;*RST"),
    # 通道选择 §SELect:CH<x> {ON|OFF}
    ("set_channel", ("1", "ON"), "SELect:CH1 ON"),
    ("set_channel", ("4", "OFF"), "SELect:CH4 OFF"),
    # 垂直挡位 §CH<x>:SCAle <NR3>
    ("set_vertical_scale", ("1", 0.001), "CH1:SCAle 0.001"),
    ("set_vertical_scale", ("4", 10.0), "CH4:SCAle 10.0"),
    # 垂直位置 §CH<x>:POSition <NR3>
    ("set_vertical_position", ("1", 0.0), "CH1:POSition 0.0"),
    ("set_vertical_position", ("2", -1.5), "CH2:POSition -1.5"),
    # 触发源 §TRIGger:A:EDGE:SOUrce {CH<x>|...}
    ("set_trigger_source", ("1",), "TRIGger:A:EDGE:SOUrce CH1"),
    ("set_trigger_source", ("3",), "TRIGger:A:EDGE:SOUrce CH3"),
    # 触发电平 §TRIGger:A:LEVel:CH<x> <NR3>
    ("set_trigger_level", ("1", 0.0), "TRIGger:A:LEVel:CH1 0.0"),
    ("set_trigger_level", ("2", -0.5), "TRIGger:A:LEVel:CH2 -0.5"),
    # 时基 §HORizontal:SCAle <NR3>
    ("set_horizontal_scale", (1e-3,), "HORizontal:SCAle 0.001"),
    ("set_horizontal_scale", (5e-10,), "HORizontal:SCAle 5e-10"),
    # 采集模式 §ACQuire:MODe
    ("set_acquisition_mode", ("AVErage",), "ACQuire:MODe AVErage"),
    ("set_acquisition_mode", ("SAMple",), "ACQuire:MODe SAMple"),
    # 平均次数 §ACQuire:NUMAVg <NR1>
    ("set_number_of_acquisitions", (16,), "ACQuire:NUMAVg 16"),
    ("set_number_of_acquisitions", (2,), "ACQuire:NUMAVg 2"),
    # 测量源 §MEASUrement:IMMed:SOUrce1 CH<x>
    ("set_meas_source", ("1",), "MEASUrement:IMMed:SOUrce1 CH1"),
    ("set_meas_source", ("4",), "MEASUrement:IMMed:SOUrce1 CH4"),
    # 阻抗 §CH<x>:TERmination {FIFty|MEG}
    ("set_impedance", ("1", "FIFty"), "CH1:TERmination FIFty"),
    ("set_impedance", ("2", "MEG"), "CH2:TERmination MEG"),
    # 测量类型 §MEASUrement:IMMed:TYPe
    ("set_meas_type", ("AMPlitude",), "MEASUrement:IMMed:TYPe AMPlitude"),
    ("set_meas_type", ("PERIod",), "MEASUrement:IMMed:TYPe PERIod"),
    ("set_meas_type", ("MAXimum",), "MEASUrement:IMMed:TYPe MAXimum"),
    ("set_meas_type", ("MINimum",), "MEASUrement:IMMed:TYPe MINimum"),
    ("set_meas_type", ("RISe",), "MEASUrement:IMMed:TYPe RISe"),
    # 测量值查询 §MEASUrement:IMMed:VALue?
    ("get_value", (), "MEASUrement:IMMed:VALue?"),
    # 测量方法 §MEASUrement:METHod {Auto|HIStogram|MINMax}
    ("set_meas_method", ("Auto",), "MEASUrement:METHod Auto"),
    # 采集状态 §ACQuire:STATE {RUN|STOP}
    ("set_acquire_state", ("RUN",), "ACQuire:STATE RUN"),
    # 停止条件 §ACQuire:STOPAfter {RUNSTop|SEQuence}
    ("set_acquire_stop_after", ("SEQuence",), "ACQuire:STOPAfter SEQuence"),
    ("set_acquire_stop_after", ("RUNSTop",), "ACQuire:STOPAfter RUNSTop"),
]


@pytest.mark.parametrize("action_name,args,expected", SCPI_CASES, ids=[c[0] for c in SCPI_CASES])
def test_scpi_assembly_matches_manual(mdo3_commands, action_name, args, expected):
    """组装后的 SCPI 字符串应与 3 Series MDO Programmer Manual 一致。"""
    action = mdo3_commands["actions"][action_name]
    actual = assemble_cmd(action, *args)
    assert actual == expected, f"{action_name}: 组装结果 {actual!r} 与手册期望 {expected!r} 不符"


# ===========================================================================
# 5. assemble_cmd 参数个数契约（错误参数返回空串）
# ===========================================================================


class TestAssembleCmdArgContract:
    """assemble_cmd 在参数个数不匹配时应返回空串（validate_args 机制）。"""

    def test_wrong_argc_returns_empty(self, mdo3_commands):
        action = mdo3_commands["actions"]["set_vertical_scale"]
        # 期望 2 个参数，只传 1 个
        assert assemble_cmd(action, "1") == ""

    def test_correct_argc_returns_nonempty(self, mdo3_commands):
        action = mdo3_commands["actions"]["set_vertical_scale"]
        assert assemble_cmd(action, "1", 0.001) == "CH1:SCAle 0.001"
