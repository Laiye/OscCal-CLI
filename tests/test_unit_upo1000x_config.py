"""优利德 UPO1000X 系列配置回归测试。

依据《UPO1000X 系列可编程数字示波器编程手册 REV.1(2023)》与服务手册的机型清单
（UPO1054X/UPO1104X/UPO1204X，编程手册另标注 UPO1000X、UPO1204X-E）：

- 全系列 4 通道、仅 1 MΩ 输入（数据手册输入阻抗 1 MΩ || 16 pF，手册无阻抗指令）；
- 显示 8 垂直 × 14 水平分格：`YINCrement = VerticalScale/25`（25 码/格）配合
  `YREFerence = 128`（8 位转换器中心），而 `:CURSor:CURAY` 只允许 [28,227]
  ——正好 200 码 = 8 格且以参考电平为中心；水平方向 `XINCrement = TimeScale/50`、
  `XORigin = -7*TimeScale`，即 700 点在触发点前 7 格起，按 50 点/格共 14 格；
- 测量为 split 模式：`:MEASure:SOURce CHANnel<n>` 选源，逐项查询 `:MEASure:<item>?`；
- 幅度用 VAMPlitude（顶端值-底端值），不用 VPP（最大值-最小值会把方波沿过冲全额计入），
  故不需要 `feature.meas_amp_scale` 换算；
- 该系列有 OVERshoot/RISetime 测量，瞬态项目两项都测；
- 没有 :SINGle 命令，单次采集 = `:TRIGger:SWEep SINGle` + `:RUN`。
"""

import json
import os
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from osccal.cli import cli
from osccal.core.auto_detect import detect_configs
from osccal.core.config_validation import normalize_token, validate_selection

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COMMANDS_DIR = PROJECT_ROOT / "commands"
PROFILES_DIR = PROJECT_ROOT / "profiles"
CALIBRATOR = PROJECT_ROOT / "calibrators" / "fluke_9500b.json"

CMD_FILE = "unit_upo1000x.json"
PROFILE_FILE = "unit_upo1000x.json"

# 手册 :MEASure:STATistic:ITEM 列出的全部 36 种波形参数
MANUAL_MEAS_ITEMS = [
    "VMAX",
    "VMIN",
    "VPP",
    "VTOP",
    "VBASe",
    "VAMPlitude",
    "VAVerage",
    "CYCVAVerage",
    "VMIDdle",
    "VRMS",
    "ACRMS",
    "CYCRMS",
    "AREa",
    "CYCAREa",
    "FREQuency",
    "PHASe",
    "PERiod",
    "OVERshoot",
    "PREShoot",
    "RISetime",
    "FALLtime",
    "PWIDth",
    "NWIDth",
    "PDUTy",
    "NDUTy",
    "PDELay",
    "NDELay",
    "PULSes",
    "FRR",
    "FRF",
    "FFR",
    "FFF",
    "LRR",
    "LRF",
    "LFR",
    "LFF",
]

ITEMS = ["amp", "dc_gain", "delta_time", "bandwidth", "transient"]


def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── 自动识别 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "model",
    [
        "UPO1000X",  # 手册 *IDN? 举例中的型号字段
        "UPO1054X",
        "UPO1104X",
        "UPO1204X",
        "UPO1204X-E",
        "upo1204x",  # 大小写不敏感
        "UPO 1204X",  # 忽略非字母数字字符
    ],
)
def test_auto_detect_matches_every_reported_model(model):
    """--auto 应为该系列每一种 *IDN? 型号选出唯一且正确的配置。"""
    idn = {
        "manufacturer": "UNI-T Technologies",
        "model": model,
        "serial": "SN20220718",
        "firmware": "00.00.01",
    }
    cmd, profile, cmd_file, profile_file = detect_configs(str(COMMANDS_DIR), str(PROFILES_DIR), idn)
    assert cmd and profile, f"{model} 未匹配到配置"
    assert os.path.basename(cmd_file) == CMD_FILE
    assert os.path.basename(profile_file) == PROFILE_FILE
    token = normalize_token(model)
    assert any(normalize_token(m) == token for m in cmd["models"])
    assert any(normalize_token(m) == token for m in profile["models"])


def test_upo1204x_and_upo1204x_e_are_not_ambiguous():
    """UPO1204X 与 UPO1204X-E 是两种型号，归一化后不能互相命中（否则 --auto 判歧义）。"""
    assert normalize_token("UPO1204X") != normalize_token("UPO1204X-E")
    models = _load(COMMANDS_DIR / CMD_FILE)["models"]
    assert models.count("UPO1204X") == 1
    assert models.count("UPO1204X-E") == 1


def test_commands_and_profile_cover_same_models():
    """指令集与 Profile 覆盖的型号集合必须完全一致。"""
    cmd_models = set(_load(COMMANDS_DIR / CMD_FILE)["models"])
    profile_models = set(_load(PROFILES_DIR / PROFILE_FILE)["models"])
    assert cmd_models == profile_models
    assert cmd_models == {"UPO1000X", "UPO1054X", "UPO1104X", "UPO1204X", "UPO1204X-E"}


# ── 指令集契约 ──────────────────────────────────────────────────────────


def test_measurement_items_match_manual_list():
    """候选测量项必须与手册列出的 36 种波形参数一致（不多不少）。"""
    items = _load(COMMANDS_DIR / CMD_FILE)["actions"]["get_value_from_item"]["args"][0]
    assert items == MANUAL_MEAS_ITEMS
    assert len(items) == 36


def test_keyword_mnemonics_are_offered_measurement_items():
    """工程用到的每个测量 keyword 都必须落在候选测量项里（否则查询助记符会写错）。"""
    cmd = _load(COMMANDS_DIR / CMD_FILE)
    items = set(cmd["actions"]["get_value_from_item"]["args"][0])
    for name in (
        "meas_amp",
        "meas_period",
        "meas_mean",
        "meas_risetime",
        "meas_pos_overshoot",
        "meas_freq",
        "meas_max",
        "meas_min",
    ):
        assert cmd["keyword"][name] in items, f"{name} 不在候选测量项中"


def test_uses_vamplitude_not_vpp():
    """幅度必须用 VAMPlitude：VPP 取最大值-最小值，会把方波沿的确定性过冲全额计入。"""
    cmd = _load(COMMANDS_DIR / CMD_FILE)
    assert cmd["keyword"]["meas_amp"] == "VAMPlitude"
    assert "VPP" in cmd["actions"]["get_value_from_item"]["args"][0]  # 手册里确实有，只是不用
    # VAMPlitude 已是标准值的峰峰值口径（顶端值-底端值），无需换算系数
    assert "meas_amp_scale" not in cmd["feature"]


def test_split_mode_commands_follow_manual():
    """split 模式：选源 + 逐项查询，指令拼写与手册一致。"""
    cmd = _load(COMMANDS_DIR / CMD_FILE)
    assert cmd["feature"] == {
        "meas": "split",
        "return_value_index": 0,
        "get_value": "ByItem",
        "set_meas": "Channel",
        # 实测该机型会静默丢弃背靠背指令（错误队列仍报 No error），故声明写入间隔
        "write_delay_ms": 50,
    }
    actions = cmd["actions"]
    assert actions["preset"]["commands"] == ["*RST\n"]
    assert actions["set_channel"]["commands"] == [":CHANnel", ":DISPlay ", "\n"]
    assert actions["set_vertical_scale"]["commands"] == [":CHANnel", ":SCALe ", "\n"]
    assert actions["set_vertical_position"]["commands"] == [":CHANnel", ":OFFSet ", "\n"]
    assert actions["set_probe_gain"]["commands"] == [":CHANnel", ":PROBe ", "X\n"]
    assert actions["set_trigger_source"]["commands"] == [":TRIGger:SOURce CHANnel", "\n"]
    assert actions["set_trigger_level"]["commands"] == [":TRIGger:LEVel ", "\n"]
    assert actions["set_horizontal_scale"]["commands"] == [":TIMebase:SCALe ", "\n"]
    assert actions["set_acquisition_mode"]["commands"] == [":ACQuire:TYPE ", "\n"]
    assert actions["set_number_of_acquisitions"]["commands"] == [":ACQuire:AVERages:COUNt ", "\n"]
    assert actions["set_meas_source"]["commands"] == [":MEASure:SOURce CHANnel", "\n"]
    assert actions["get_value_from_item"]["commands"] == [":MEASure:", "?\n"]
    # 手册没有 :SINGle 命令：单次采集由扫描模式 + :RUN 完成
    assert actions["set_acquire_stop_after"]["commands"] == [":TRIGger:SWEep ", "\n"]
    assert actions["set_acquire_state"]["commands"] == [":", "\n"]
    assert "set_impedance" not in actions  # 该系列只有 1MΩ 输入
    assert cmd["keyword"]["acquire_stop_after_single"] == "SINGle"
    assert cmd["keyword"]["acquire_state_run"] == "RUN"
    # 采集模式取值须与手册一致（平均次数以 2 的幂步进，2~8192）
    assert set(actions["set_acquisition_mode"]["args"][0]) == {
        "NORMal",
        "AVERage",
        "PEAKdetect",
        "HRESolution",
    }


# ── Profile 契约 ────────────────────────────────────────────────────────


def test_profile_matches_series_hardware():
    """Profile 的几何/探头/量程参数须与手册推导一致。"""
    profile = _load(PROFILES_DIR / PROFILE_FILE)
    assert profile["manufacturer"] == "UNI-T"
    assert profile["channels"] == 4  # 全系列标配 4 通道
    assert profile["imp_has_50"] is False  # 1 MΩ || 16 pF，无 50Ω 挡
    # 垂直 8 格：25 码/格 × 200 码（CURAY [28,227]）且以 YREFerence=128 为中心
    assert profile["vertical_div"] == 8
    # 水平 14 格：XORigin=-7×TimeScale（触发点在中心）且 XINCrement=TimeScale/50
    assert profile["horizontal_div"] == 14
    assert profile["probe_default"] == 10  # 出厂探头衰减 10X，需置 1X 直连
    assert profile["init_time"] >= 5
    assert profile["calibration_limits"]["bandwidth"]["min_mhz"] == 50  # 系列最低带宽 UPO1054X
    for table in ("delta_amp", "dc_gain", "delta_time", "bandwidth"):
        points = profile["points"][table]
        assert points
        assert points == sorted(points)


def test_vertical_points_follow_1_2_5_within_scope_range():
    """垂直挡位 500 µV/div~20 V/div（1-2-5）；点表从 1 mV/div 起，不超出量程。"""
    profile = _load(PROFILES_DIR / PROFILE_FILE)
    for table in ("delta_amp", "dc_gain"):
        points = profile["points"][table]
        assert points[0] == 0.001
        assert points[-1] == 10.0
        for value in points:
            exponent = int(f"{value:e}".split("e")[1])
            mantissa = round(value / 10.0**exponent, 6)
            assert mantissa in (1.0, 2.0, 5.0), f"{value} 不符合 1-2-5 序列"
            assert 500e-6 <= value <= 20.0, f"{value} 超出 500 µV/div~20 V/div"


def test_delta_time_points_follow_instrument_timebase_sequence():
    """时基点表按实机确认的 1-2-5 序列排列（首档保留手册列出的 25 ns/div）。

    手册 `:TIMebase:SCALe` 举例列出 1/2/5/10/25 ns…，早期实现据此按 1-2.5-5 排列，
    实机确认该机型档位按 **1-2-5** 步进（10/20/50/100/200/500…），只有 25 ns/div
    一档是 2.5 步进，故点表为 10 ns ～ 20 ms 共 20 点，避免档位被钳位后标准值与
    实际时基不符而报出虚假大误差。
    """
    points = _load(PROFILES_DIR / PROFILE_FILE)["points"]["delta_time"]
    assert len(points) == 20
    assert points == sorted(points)
    off_sequence = [
        value
        for value in points
        if round(value / 10.0 ** int(f"{value:e}".split("e")[1]), 6) not in (1.0, 2.0, 5.0)
    ]
    assert off_sequence == [25e-9], f"除 25 ns/div 外都应落在 1-2-5 序列上: {off_sequence}"
    assert points[0] == 10e-9
    assert points[-1] == 20e-3


# ── 执行前校验 ──────────────────────────────────────────────────────────


def _selection_errors(items, probe="9530"):
    return validate_selection(
        _load(COMMANDS_DIR / CMD_FILE),
        _load(PROFILES_DIR / PROFILE_FILE),
        _load(CALIBRATOR),
        ["1"],
        list(items),
        probe,
        20e6,
        5e6,
    )


def test_preflight_accepts_all_items_with_1m_ohm_probe():
    """五项校准在 9530（各模式均支持 1MΩ）下全部可用。"""
    assert _selection_errors(ITEMS) == []


def test_preflight_rejects_50_ohm_only_probe():
    """9560 的 MARK/SIN/EDGE 仅支持 50Ω，而该系列只有 1MΩ，应在执行前被拒。"""
    errors = _selection_errors(ITEMS, probe="9560")
    assert any("阻抗不匹配" in e for e in errors), errors
    # amp/dc_gain 走 SQU/DC，9560 支持 1MΩ，不应被拒
    assert not any("项目 amp" in e or "项目 dc_gain" in e for e in errors), errors


def test_preflight_rejects_channel_out_of_range():
    """该系列只有 4 个通道。"""
    errors = validate_selection(
        _load(COMMANDS_DIR / CMD_FILE),
        _load(PROFILES_DIR / PROFILE_FILE),
        _load(CALIBRATOR),
        ["5"],
        ["amp"],
        "9530",
        20e6,
        5e6,
    )
    assert any("通道" in e for e in errors), errors


# ── CLI 端到端（mock 仪器） ─────────────────────────────────────────────


class _RecordingInst:
    """记录写入/查询指令的假仪器，测量查询返回合法的一行响应。"""

    def __init__(self, idn: str):
        self.idn = idn
        self.written: list[str] = []
        self.timeout = None

    def write(self, cmd: str):
        self.written.append(cmd)

    def query(self, cmd: str) -> str:
        self.written.append(cmd)
        if cmd.strip() == "*IDN?":
            return self.idn + "\n"
        return "1.0\n"

    def close(self):
        pass


@pytest.fixture
def upo_scope(monkeypatch):
    """把 CLI 的连接函数换成记录型假仪器（示波器上报 UPO1204X）。"""
    import osccal.cli as cli_mod
    import osccal.core.storage as storage_mod

    created: dict[str, _RecordingInst] = {}

    def fake_connect_visa(resource):
        # 按资源串精确区分两台仪器（示波器走 TCPIP，其地址里也含 "19" 字样）
        is_cal = resource == "GPIB0::19::INSTR"
        if is_cal:
            inst = _RecordingInst("FLUKE,9500B,SIM,4.12")
            idn = {"manufacturer": "FLUKE", "model": "9500B", "serial": "SIM", "firmware": "v"}
        else:
            inst = _RecordingInst("UNI-T Technologies,UPO1204X,SN20220718,00.00.01")
            idn = {"manufacturer": "UNI-T", "model": "UPO1204X", "serial": "SN", "firmware": "v"}
        created["cal" if is_cal else "osc"] = inst
        return inst, idn

    monkeypatch.setattr(cli_mod, "connect_visa", fake_connect_visa)
    monkeypatch.setattr(time, "sleep", lambda _: None)

    saved: dict = {}

    def fake_save(results, metadata, *, filepath=None):
        saved["results"] = results
        saved["metadata"] = metadata
        return ""

    monkeypatch.setattr(storage_mod, "save_calibration_data", fake_save)
    return created, saved


def _args(items):
    return [
        "calibrate",
        "--osc",
        f"commands/{CMD_FILE}",
        "--profile",
        f"profiles/{PROFILE_FILE}",
        "--calibrator",
        "calibrators/fluke_9500b.json",
        "--probe",
        "9530",
        "--channel",
        "1",
        "--items",
        items,
        "--resource-cal",
        "GPIB0::19::INSTR",
        "--resource-osc",
        "TCPIP0::192.168.20.11::inst0::INSTR",
    ]


def test_cli_sends_manual_scpi_for_amplitude(upo_scope):
    """幅度校准应按手册下发 CHANnel:DISPlay/PROBe/SCALe、TRIGger、MEASure 指令。"""
    created, saved = upo_scope
    result = CliRunner().invoke(cli, _args("amp"), input="n\n")
    assert result.exit_code == 0, result.output

    written = created["osc"].written
    assert "*RST\n" in written
    # amp 必须显式选方波，不能依赖校准仪恰好停在 SQU（上电/复位后是默认形状）
    assert "SOUR:SCOP:SHAP SQU" in created["cal"].written
    assert ":CHANnel1:DISPlay ON\n" in written
    assert ":CHANnel1:PROBe 1X\n" in written  # 出厂 10X 探头置为 1X，与校准仪直连匹配
    assert ":TRIGger:SOURce CHANnel1\n" in written
    assert ":CHANnel1:SCALe 0.001\n" in written
    assert ":TIMebase:SCALe 0.001\n" in written
    assert ":ACQuire:TYPE AVERage\n" in written
    assert ":MEASure:SOURce CHANnel1\n" in written
    assert ":MEASure:VAMPlitude?\n" in written
    # 每个挡位都微调触发电平（0.1 格、符号交替），迫使平均序列重新开始
    nudges = [c for c in written if c.startswith(":TRIGger:LEVel ")]
    assert nudges, "每个挡位后应写入一次触发电平微调"
    assert nudges[0] == ":TRIGger:LEVel 0.0001\n"
    assert nudges[1] == ":TRIGger:LEVel -0.0002\n"
    assert len(set(nudges)) == len(nudges), "相邻挡位的微调值不应重复（否则平均不会重启）"
    # 该系列只有 1MΩ 输入，指令集不含 set_impedance，实际也不应下发阻抗指令
    assert not any("IMP" in c.upper() for c in written)
    assert not any(":MEASure:VPP?" in c for c in written), "应使用 VAMPlitude 而不是 VPP"
    assert "amp" in saved["results"]
    # 假仪器返回 1.0；VAMPlitude 已是峰峰值口径，不应有任何换算
    assert saved["results"]["amp"][0]["measured"] == pytest.approx(1.0)
    assert saved["metadata"]["profile_file"] == PROFILE_FILE


def test_cli_transient_measures_risetime_and_overshoot(upo_scope):
    """该系列有 OVERshoot 测量：瞬态项目两项都测，过冲列不是"不适用"。"""
    created, saved = upo_scope
    result = CliRunner().invoke(cli, _args("transient"), input="n\n")
    assert result.exit_code == 0, result.output
    assert "不适用" not in result.output

    written = created["osc"].written
    assert ":MEASure:RISetime?\n" in written
    assert ":MEASure:OVERshoot?\n" in written
    # 手册没有 :SINGle 命令：单次扫描模式 + :RUN 触发一次采集
    assert ":TRIGger:SWEep SINGle\n" in written
    assert ":RUN\n" in written
    assert ":CHANnel1:OFFSet 0.4\n" in written  # OFFSet 单位是伏特：2 格 × 0.2 V/div

    row = saved["results"]["transient"][0]
    assert row["risetime_ns"] > 0
    assert row["pos_overshoot"] == pytest.approx(1.0), "有正过冲测量时必须记录数值"
    assert row["edge_speed_ps"] == pytest.approx(500.0)  # 9530 的 1MΩ 最慢沿
