"""泰克 TBS1000B/EDU 与 TBS1000/TDS1000/TDS2000/TPS2000 系列配置回归测试。

依据 TBS1000/B/EDU, TDS2000/B/C, TDS1000/B/C-EDU, TDS200, TPS2000/B 系列编程手册
（077-044403 Rev B）：

- 该系列仅 1MΩ 输入，手册中不存在 CH<x>:TERmination/CH<x>:IMPedance 指令；
- 显示 8 垂直 × 10 水平分格（手册 CURSor HBArs UNIts DIVS 注明"屏幕底部为 -4 格"）；
- 垂直挡位 2 mV~5 V/div（1-2-5），水平时基为 1-2.5-5 序列（非 1-2-4-10），
  因此 Δt 点表按 1-2.5-5 排列；
- FACtory 会把 HEADer 置为 ON，查询响应带表头，故 return_value_index = 1；
- 指令集分两份：TBS1000B/EDU 使用扩展测量类型（含 AMPlitude/POVERshoot），
  其余机型只有基本类型（无 AMPlitude/POVERshoot），因此幅度改用 PK2pk，
  并且不提供 set_acquire_stop_after，使瞬态项目在执行前校验阶段被拒绝。
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

GROUP1_CMD = "tektronix_tbs1000b.json"
GROUP2_CMD = "tektronix_tds1000_tds2000.json"
GROUP1_PROFILE = "tektronix_tbs1000b.json"
GROUP2_2CH_PROFILE = "tektronix_tds1000_tds2000_2ch.json"
GROUP2_4CH_PROFILE = "tektronix_tds1000_tds2000_4ch.json"


def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _all_models(directory: Path) -> dict[str, list[str]]:
    models: dict[str, list[str]] = {}
    for fpath in sorted(directory.glob("*.json")):
        data = _load(fpath)
        if isinstance(data.get("models"), list):
            models[fpath.name] = data["models"]
    return models


# ── 自动识别 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "model,expected_cmd,expected_profile",
    [
        ("TBS1202B", GROUP1_CMD, GROUP1_PROFILE),
        ("TBS1052B-EDU", GROUP1_CMD, GROUP1_PROFILE),
        ("TBS1102", GROUP2_CMD, GROUP2_2CH_PROFILE),
        ("TBS 1102", GROUP2_CMD, GROUP2_2CH_PROFILE),  # 真机 *IDN? 上报含空格的写法
        ("TBS1022", GROUP2_CMD, GROUP2_2CH_PROFILE),
        ("TDS1002C-EDU", GROUP2_CMD, GROUP2_2CH_PROFILE),
        ("TDS2001C", GROUP2_CMD, GROUP2_2CH_PROFILE),
        ("TDS2022B", GROUP2_CMD, GROUP2_2CH_PROFILE),
        ("TPS2012B", GROUP2_CMD, GROUP2_2CH_PROFILE),
        ("TDS2014", GROUP2_CMD, GROUP2_4CH_PROFILE),
        ("TDS2024C", GROUP2_CMD, GROUP2_4CH_PROFILE),
        ("TPS2024B", GROUP2_CMD, GROUP2_4CH_PROFILE),
    ],
)
def test_auto_detect_matches_series(model, expected_cmd, expected_profile):
    """--auto 应为该系列每个型号选出唯一且正确的指令集与特征文件。"""
    idn = {"manufacturer": "TEKTRONIX", "model": model, "serial": "S", "firmware": "v"}
    cmd, profile, cmd_file, profile_file = detect_configs(str(COMMANDS_DIR), str(PROFILES_DIR), idn)
    assert cmd and profile, f"{model} 未匹配到配置"
    assert os.path.basename(cmd_file) == expected_cmd
    assert os.path.basename(profile_file) == expected_profile
    # 型号匹配忽略大小写与空格等非字母数字字符（"TBS 1102" ≡ "TBS1102"）
    token = normalize_token(model)
    assert any(normalize_token(m) == token for m in profile["models"])
    assert any(normalize_token(m) == token for m in cmd["models"])


def test_no_model_is_claimed_twice():
    """同一型号不能出现在两个指令集/两个 Profile 中，否则 --auto 会判定歧义。"""
    for directory in (COMMANDS_DIR, PROFILES_DIR):
        seen: dict[str, str] = {}
        for fname, models in _all_models(directory).items():
            for model in models:
                assert model not in seen, f"{model} 同时出现在 {seen.get(model)} 与 {fname}"
                seen[model] = fname


def test_this_series_commands_and_profiles_cover_same_models():
    """本系列两份指令集与三个 Profile 覆盖的型号集合必须完全一致。"""
    cmd_models = {
        m for fname in (GROUP1_CMD, GROUP2_CMD) for m in _load(COMMANDS_DIR / fname)["models"]
    }
    profile_models = {
        m
        for fname in (GROUP1_PROFILE, GROUP2_2CH_PROFILE, GROUP2_4CH_PROFILE)
        for m in _load(PROFILES_DIR / fname)["models"]
    }
    assert cmd_models == profile_models
    assert len(cmd_models) == 49  # 手册适用型号中除 TDS210/220/224 外的全部


# ── 指令集契约 ──────────────────────────────────────────────────────────


def test_group2_uses_manual_commands_and_crms():
    """非 TBS1000B/EDU 机型：使用手册中的基本命令，幅度测量用 CRMs（实机验证）。"""
    cmd = _load(COMMANDS_DIR / GROUP2_CMD)
    keyword = cmd["keyword"]
    # 该组机型没有 AMPlitude；PK2pk 会把方波沿的峰化/过冲全额计入（实机偏高 1.3~5.3%），
    # 改用 CRMs（第一周期真有效值），对称方波时等于幅度 = 标准值峰峰值的一半
    assert keyword["meas_amp"] == "CRMs"
    assert cmd["feature"]["meas_amp_scale"] == 2.0
    assert keyword["meas_period"] == "PERIod"
    assert keyword["meas_mean"] == "MEAN"
    assert keyword["meas_max"] == "MAXImum"
    assert keyword["meas_min"] == "MINImum"
    assert keyword["acquire_stop_after_single"] == "SEQuence"
    assert keyword["acquire_state_run"] == "RUN"
    # 该组机型没有正过冲测量：省略 meas_pos_overshoot，瞬态项目只记录上升时间
    assert "meas_pos_overshoot" not in keyword
    assert cmd["feature"]["return_value_index"] == 1  # FACtory 打开 HEADer

    actions = cmd["actions"]
    assert actions["preset"]["commands"] == ["FACtory"]
    assert actions["set_channel"]["commands"] == ["SELect:CH", " "]
    assert actions["set_vertical_scale"]["commands"] == ["CH", ":SCAle "]
    assert actions["set_vertical_position"]["commands"] == ["CH", ":POSition "]
    assert actions["set_probe_gain"]["commands"] == ["CH", ":PRObe "]
    assert actions["set_trigger_source"]["commands"] == ["TRIGger:MAIn:EDGE:SOUrce CH"]
    assert actions["set_trigger_level"]["commands"] == ["TRIGger:MAIn:LEVel "]
    assert actions["set_horizontal_scale"]["commands"] == ["HORizontal:MAIn:SCAle "]
    assert actions["set_acquisition_mode"]["commands"] == ["ACQuire:MODe "]
    assert actions["set_number_of_acquisitions"]["commands"] == ["ACQuire:NUMAVg "]
    assert actions["set_meas_source"]["commands"] == ["MEASUrement:IMMed:SOUrce1 CH"]
    assert actions["set_meas_type"]["commands"] == ["MEASUrement:IMMed:TYPe "]
    assert actions["get_value"]["commands"] == ["MEASUrement:IMMed:VALue?"]
    assert "set_impedance" not in actions  # 该系列无 50Ω 输入
    # 瞬态项目仍可用（只测上升时间），故采集控制指令必须齐全
    assert actions["set_acquire_state"]["commands"] == ["ACQuire:STATE "]
    assert actions["set_acquire_stop_after"]["commands"] == ["ACQuire:STOPAfter "]
    assert "RISe" in actions["set_meas_type"]["args"][0]
    assert "CRMs" in actions["set_meas_type"]["args"][0]


def test_group1_supports_extended_measurements():
    """TBS1000B/EDU 机型支持 AMPlitude/POVERshoot，瞬态项目可用。"""
    cmd = _load(COMMANDS_DIR / GROUP1_CMD)
    assert cmd["keyword"]["meas_amp"] == "AMplitude"
    assert cmd["keyword"]["meas_pos_overshoot"] == "POVERshoot"
    assert "set_acquire_stop_after" in cmd["actions"]
    assert "set_acquire_state" in cmd["actions"]
    types = cmd["actions"]["set_meas_type"]["args"][0]
    for name in ("AMplitude", "POVERshoot", "PK2pk", "MEAN", "PERIod", "RISe"):
        assert name in types


def test_measurement_types_stay_within_manual_scope():
    """候选测量类型必须落在手册为该组机型列出的范围内，且覆盖工程用到的类型。"""
    group1 = set(_load(COMMANDS_DIR / GROUP1_CMD)["actions"]["set_meas_type"]["args"][0])
    group2 = set(_load(COMMANDS_DIR / GROUP2_CMD)["actions"]["set_meas_type"]["args"][0])
    extended = {"AMplitude", "POVERshoot", "NOVERshoot", "BURSTWIDth"}
    assert extended <= group1
    assert not extended & group2  # 扩展类型仅 TBS1000B/EDU 支持

    for cmd_file, types in ((GROUP1_CMD, group1), (GROUP2_CMD, group2)):
        keyword = _load(COMMANDS_DIR / cmd_file)["keyword"]
        for name in (
            "meas_amp",
            "meas_period",
            "meas_mean",
            "meas_risetime",
            "meas_max",
            "meas_min",
        ):
            assert keyword[name] in types, f"{cmd_file} 的 {name} 不在候选类型中"
        assert "PK2pk" in types


# ── Profile 契约 ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "profile_file,channels,min_mhz,averages",
    [
        (GROUP1_PROFILE, 2, 50, 16),  # AMPlitude 测量，噪声不直接抬高结果，保持默认 16
        (GROUP2_2CH_PROFILE, 2, 25, 64),  # PK2pk，需更多平均把波形"压薄"
        (GROUP2_4CH_PROFILE, 4, 70, 64),
    ],
)
def test_profile_matches_series_hardware(profile_file, channels, min_mhz, averages):
    profile = _load(PROFILES_DIR / profile_file)
    assert profile["manufacturer"] == "Tektronix"
    assert profile["channels"] == channels
    assert profile["imp_has_50"] is False
    assert profile["vertical_div"] == 8  # 屏幕底部为 -4 格
    assert profile["horizontal_div"] == 10
    assert profile["probe_default"] == 10  # 出厂无源探头 10X，需置 1X 直连
    assert profile.get("averages", 16) == averages
    assert profile["calibration_limits"]["bandwidth"]["min_mhz"] == min_mhz
    for table in ("delta_amp", "dc_gain", "delta_time", "bandwidth"):
        points = profile["points"][table]
        assert points, f"{table} 点表为空"
        assert points == sorted(points)
    # 垂直挡位 2 mV~5 V/div（1-2-5），不含 1 mV/div 与 10 V/div
    for table in ("delta_amp", "dc_gain"):
        assert profile["points"][table][0] == 0.002
        assert profile["points"][table][-1] == 5.0
    # 带宽测量点不进入 20 MHz 限带区（2.00~4.99 mV/div）
    assert min(profile["points"]["bandwidth"]) >= 0.005
    assert 2e6 <= profile["bd_step"] <= 1e7


@pytest.mark.parametrize("profile_file", [GROUP1_PROFILE, GROUP2_2CH_PROFILE, GROUP2_4CH_PROFILE])
def test_delta_time_points_follow_1_2_5_sequence(profile_file):
    """水平时基按 1-2.5-5 排列，点表不能出现 20/40/800 ns 这类会被钳位的值。"""
    points = _load(PROFILES_DIR / profile_file)["points"]["delta_time"]
    assert len(points) == 20
    for value in points:
        exponent = int(f"{value:e}".split("e")[1])
        mantissa = round(value / 10.0**exponent, 6)
        assert mantissa in (1.0, 2.5, 5.0), f"{value} 不符合 1-2.5-5 序列"
    # 最快 10 ns/div、最慢 25 ms/div：各机型最快 2.5/5 ns、最慢 50 s，均在范围内
    assert points[0] == 10e-9
    assert points[-1] == 25e-3


# ── 执行前校验 ──────────────────────────────────────────────────────────


def _selection_errors(cmd_file, profile_file, items, probe="9530"):
    cmd = _load(COMMANDS_DIR / cmd_file)
    profile = _load(PROFILES_DIR / profile_file)
    return validate_selection(
        cmd, profile, _load(CALIBRATOR), ["1"], list(items), probe, 100e6, 5e6
    )


def test_group2_preflight_accepts_all_items():
    """非 TBS1000B/EDU 机型：五项目均可执行；瞬态只测上升时间（无正过冲测量）。"""
    items = ["amp", "dc_gain", "delta_time", "bandwidth", "transient"]
    assert _selection_errors(GROUP2_CMD, GROUP2_4CH_PROFILE, items) == []
    assert _selection_errors(GROUP2_CMD, GROUP2_2CH_PROFILE, items) == []


def test_group1_preflight_accepts_all_items():
    """TBS1000B/EDU 机型：五项校准均可执行（1MΩ 需 9530 探头）。"""
    items = ["amp", "dc_gain", "delta_time", "bandwidth", "transient"]
    assert _selection_errors(GROUP1_CMD, GROUP1_PROFILE, items) == []
    # 9560 的 MARK/SIN/EDGE 仅支持 50Ω，而该系列只有 1MΩ，应被拒绝
    errors = _selection_errors(GROUP1_CMD, GROUP1_PROFILE, items, probe="9560")
    assert any("阻抗不匹配" in e for e in errors), errors


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
        return ":MEASUREMENT:IMMED:VALUE 1.0E+0"

    def close(self):
        pass


@pytest.fixture
def tds_scope(monkeypatch):
    """把 CLI 的连接函数换成记录型假仪器（示波器型号 TDS2024C）。"""
    import osccal.cli as cli_mod
    import osccal.core.storage as storage_mod

    created: dict[str, _RecordingInst] = {}

    def fake_connect_visa(resource):
        is_cal = "19" in resource
        idn = "FLUKE,9500B,SIM,4.12" if is_cal else "TEKTRONIX,TDS2024C,SIMS,CF:91.1CT"
        inst = _RecordingInst(idn)
        created["cal" if is_cal else "osc"] = inst
        mfr, model = ("FLUKE", "9500B") if is_cal else ("TEKTRONIX", "TDS2024C")
        return inst, {"manufacturer": mfr, "model": model, "serial": "SIM", "firmware": "v"}

    monkeypatch.setattr(cli_mod, "connect_visa", fake_connect_visa)
    monkeypatch.setattr(time, "sleep", lambda _: None)

    saved: dict = {}

    def fake_save(results, metadata, *, filepath=None):
        saved["results"] = results
        saved["metadata"] = metadata
        return ""

    monkeypatch.setattr(storage_mod, "save_calibration_data", fake_save)
    return created, saved


def _group2_args(profile_file, items):
    return [
        "calibrate",
        "--osc",
        f"commands/{GROUP2_CMD}",
        "--profile",
        f"profiles/{profile_file}",
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
        "GPIB0::10::INSTR",
    ]


def test_cli_sends_manual_scpi_for_group2_amplitude(tds_scope):
    """幅度校准应按手册下发 SELect/CH:PRObe/CH:SCAle/TRIGger:MAIn/MEASUrement 指令。"""
    created, saved = tds_scope
    result = CliRunner().invoke(cli, _group2_args(GROUP2_4CH_PROFILE, "amp"), input="n\n")
    assert result.exit_code == 0, result.output

    written = created["osc"].written
    assert "FACtory" in written
    assert "SELect:CH1 ON" in written
    assert "CH1:PRObe 1" in written  # 出厂 10X 探头置为 1X，与校准仪直连匹配
    assert "TRIGger:MAIn:EDGE:SOUrce CH1" in written
    assert "HORizontal:MAIn:SCAle 0.001" in written
    assert "CH1:SCAle 0.002" in written
    assert "ACQuire:MODe AVErage" in written
    # 低挡位噪声/峰化明显，该组 Profile 把平均次数提到 64（本系列合法值 4/16/64/128）
    assert "ACQuire:NUMAVg 64" in written
    # 每个挡位都微调触发电平（0.1 格、符号交替），迫使平均序列重新开始
    nudges = [c for c in written if c.startswith("TRIGger:MAIn:LEVel ")]
    assert nudges, "每个挡位后应写入一次触发电平微调"
    assert nudges[0] == "TRIGger:MAIn:LEVel 0.0002"
    assert nudges[1] == "TRIGger:MAIn:LEVel -0.0005"
    assert len({c for c in nudges}) == len(nudges), "相邻挡位的微调值不应重复（否则平均不会重启）"
    assert all("TERmination" not in c and "IMPedance" not in c for c in written)
    assert all("TRIGger:A:" not in c for c in written)  # 该系列用 TRIGger:MAIn
    assert any("MEASUrement:IMMed:SOUrce1 CH1" in c for c in written)
    assert any("MEASUrement:IMMed:TYPe CRMs" in c for c in written)
    assert not any("TYPe PK2pk" in c for c in written), "已改用 CRMs，不应再下发 PK2pk"
    assert any("MEASUrement:IMMed:VALue?" in c for c in written)
    assert "amp" in saved["results"]
    # 假仪器返回 1.0（CRMs 口径 = 幅度），换算到峰峰值口径后应为 2.0
    assert saved["results"]["amp"][0]["measured"] == pytest.approx(2.0)
    assert saved["metadata"]["profile_file"] == GROUP2_4CH_PROFILE


def test_cli_transient_without_overshoot_measures_risetime(tds_scope):
    """非 TBS1000B/EDU 机型：瞬态仍执行，只测上升时间，过冲记为"不适用"。"""
    created, saved = tds_scope
    result = CliRunner().invoke(cli, _group2_args(GROUP2_4CH_PROFILE, "transient"), input="n\n")
    assert result.exit_code == 0, result.output
    assert "不适用" in result.output
    assert "未声明正过冲测量" in result.output  # 执行时的提示（rich 会按宽度折行，只断言片段）

    written = created["osc"].written
    assert any("MEASUrement:IMMed:TYPe RISe" in c for c in written)
    assert not any("POVERshoot" in c for c in written)  # 不下发机型不支持的测量类型
    assert "ACQuire:STOPAfter SEQuence" in written
    assert "ACQuire:STATE RUN" in written

    row = saved["results"]["transient"][0]
    assert row["risetime_ns"] > 0, "上升时间应被测量"
    assert row["pos_overshoot"] is None, "无正过冲测量的机型过冲应为 null"
    assert row["edge_speed_ps"] == pytest.approx(500.0)  # 9530 的 1MΩ 最慢沿


def test_excel_transient_without_overshoot_shows_not_applicable():
    """Excel 报告的过冲列写入"不适用"，上升时间仍按显示精度整理。"""
    from openpyxl import Workbook

    from osccal.core.export import _create_data_sheet
    from osccal.core.table_configs import EXCEL_ITEM_CONFIGS

    wb = Workbook()
    row = {"channel": "1", "risetime_ns": 0.7, "pos_overshoot": None, "edge_speed_ps": 500.0}
    _create_data_sheet(wb, "transient", EXCEL_ITEM_CONFIGS["transient"], [row])
    ws = wb["上升时间及过冲"]
    assert ws.cell(2, 2).value == 0.7
    assert ws.cell(2, 3).value == "不适用"
    assert ws.cell(2, 3).number_format == "General"  # 文本单元格不做数值格式
    assert ws.cell(2, 4).value == 500


def test_cli_auto_recognises_reported_model_with_space(monkeypatch):
    """真机回归：示波器上报 "TEKTRONIX,TBS 1102,..."（型号含空格）时 --auto 必须成功。

    现场 IDN：TEKTRONIX,TBS 1102,C030565,CF:91.1CT FV:v26.02；
    校准仪上报 9500（同一台 9500B 的不同固件写法）。
    """
    import sys
    import types

    import osccal.core.storage as storage_mod

    scpi_log: list[str] = []

    class AutoInst:
        def __init__(self, idn: str):
            self.idn = idn
            self.timeout = None

        def write(self, cmd: str):
            scpi_log.append(cmd)

        def query(self, cmd: str) -> str:
            scpi_log.append(cmd)
            if cmd.strip() == "*IDN?":
                return self.idn + "\n"
            if "ROUT:FITT?" in cmd.upper():
                return "9530\n"
            return ":MEASUREMENT:IMMED:VALUE 1.0E+0\n"

        def close(self):
            pass

    class AutoRM:
        def list_resources(self):
            return ["USB0::0x0699::0x03B1::C030565::INSTR", "GPIB0::19::INSTR"]

        def open_resource(self, resource):
            if "19" in resource:
                return AutoInst("FLUKE,9500,471475627,4.12")
            return AutoInst("TEKTRONIX,TBS 1102,C030565,CF:91.1CT FV:v26.02")

        def close(self):
            pass

    monkeypatch.setitem(sys.modules, "pyvisa", types.SimpleNamespace(ResourceManager=AutoRM))
    monkeypatch.setattr(time, "sleep", lambda _: None)

    saved: dict = {}

    def fake_save(results, metadata, *, filepath=None):
        saved["results"] = results
        saved["metadata"] = metadata
        return ""

    monkeypatch.setattr(storage_mod, "save_calibration_data", fake_save)

    runner = CliRunner()
    # 输入：确认执行(y)、通道(0=CH1)、项目(1=amp)、不再继续(n)
    result = runner.invoke(
        cli,
        ["calibrate", "--auto", "--calibrator", "calibrators/fluke_9500b.json"],
        input="y\n0\n1\nn\n",
    )
    assert result.exit_code == 0, result.output
    assert "未找到与型号" not in result.output
    assert GROUP2_CMD in result.output  # 自动识别摘要列出实际使用的配置
    assert GROUP2_2CH_PROFILE in result.output
    assert "amp" in saved["results"]
    assert saved["metadata"]["profile_file"] == GROUP2_2CH_PROFILE
