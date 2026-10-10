"""模拟校准集成测试：无需真实硬件即可跑通全部校准器链路。

通过 simulate_calibrate 的模拟仪器（校准仪 write 更新共享状态、示波器按
一阶低通模型响应）验证每个校准器端到端可运行且产出合理结果。
"""

import time
from types import SimpleNamespace

import pytest

from simulate_calibrate import run_calibration

# 各校准项目独立运行 + 全项目（快速模式，无 sleep）
ITEM_CASES = [
    "all",
    "amp",
    "dc_gain",
    "delta_time",
    "bandwidth",
    "transient",
    "amp,dc_gain",
]


def _make_args(
    items: str,
    channel: str = "1",
    sim_bandwidth: float = 200.0,
    commands: str = "tektronix_mdo3",
    profile: str = "tektronix_mdo34",
    probe: str = "9560",
) -> SimpleNamespace:
    return SimpleNamespace(
        commands=commands,
        profile=profile,
        calibrator="fluke_9500b",
        items=items,
        channel=channel,
        probe=probe,
        bandwidth=100.0,
        bd_step=20.0,
        sim_bandwidth=sim_bandwidth,
    )


@pytest.fixture
def fast_mode(monkeypatch):
    """快速模式：禁用 time.sleep，秒级完成模拟校准。"""
    monkeypatch.setattr(time, "sleep", lambda x: None)


@pytest.mark.parametrize("items", ITEM_CASES, ids=lambda v: v.replace(",", "_"))
def test_sim_calibration_items(fast_mode, items):
    inst_osc, inst_cal, profile, all_results = run_calibration(_make_args(items))
    assert all_results, "未产生任何校准结果"
    for key, rows in all_results.items():
        assert rows, f"{key} 无数据点"


def test_sim_transient_produces_values(fast_mode):
    _, _, _, all_results = run_calibration(_make_args("transient"))
    row = all_results["transient"][0]
    assert row["risetime_ns"] > 0, "上升时间应为正数"
    assert row["pos_overshoot"] >= 0, "过冲应为非负数"
    assert row["edge_speed_ps"] == 70.0, "9560 探头上升时间应为 70ps"


def test_sim_multi_channel(fast_mode):
    _, _, _, all_results = run_calibration(_make_args("amp", channel="1,2"))
    assert "amp_ch1" in all_results and "amp_ch2" in all_results
    assert len(all_results["amp_ch1"]) == len(all_results["amp_ch2"])


def test_sim_bandwidth_upward_scan(fast_mode):
    """正常情况：模拟带宽高于起始带宽，向上扫描应得到 ~sim_bandwidth。"""
    _, _, _, all_results = run_calibration(_make_args("bandwidth", sim_bandwidth=200.0))
    bws = [r["bandwidth_mhz"] for r in all_results["bandwidth"]]
    assert all(190 <= bw <= 210 for bw in bws), f"带宽应接近 200MHz，实际 {bws}"


def test_sim_bandwidth_below_start_downward_scan(fast_mode):
    """项4边界修复：模拟带宽(60MHz)低于起始带宽(100MHz)时，
    应向下扫描得到 ~60MHz 而非错误的 start_bd - bd_step。"""
    _, _, _, all_results = run_calibration(_make_args("bandwidth", sim_bandwidth=60.0))
    bws = [r["bandwidth_mhz"] for r in all_results["bandwidth"]]
    assert all(50 <= bw <= 70 for bw in bws), f"带宽应接近 60MHz，实际 {bws}"


def test_sim_bandwidth_bisect_efficiency(fast_mode):
    """方案A（指数粗定位+栅格二分）：带宽远高于起始带宽时测量次数大幅减少。

    1GHz 场景下线性扫描需 ~337 次 set_freq（7 挡位合计），二分应 ≤ 200 次，
    且结果与线性一致（防扫描回归为线性或结果漂移）。
    """
    inst_osc, inst_cal, _, all_results = run_calibration(
        _make_args("bandwidth", sim_bandwidth=1000.0)
    )
    writes = sum(
        1
        for direction, cmd in inst_cal.log
        if direction == "W" and cmd.strip().upper().startswith("SOUR:FREQ")
    )
    assert writes <= 200, f"二分扫描测量次数过多（{writes}），疑似退化为线性扫描"
    bws = [r["bandwidth_mhz"] for r in all_results["bandwidth"]]
    assert all(990 <= bw <= 1010 for bw in bws), f"带宽应接近 1000MHz，实际 {bws}"


# ── 优利德 UPO1000X 方言（完整助记符 + 前导冒号） ────────────────────────
#
# 该系列用 :CHANnel<n>:SCALe、:ACQuire:TYPE、:MEASure:SOURce CHANnel<n> 等完整
# 助记符写法，与泰克/是德的缩写前缀不同，需要模拟器单独解析，否则垂直挡位、
# 触发电平等状态全部丢失，自动垂直位置调整等行为就不再被模拟。


def _upo_args(items: str, sim_bandwidth: float = 100.0) -> SimpleNamespace:
    # 该系列仅 1MΩ 输入，必须用 9530 探头（各模式均支持 1MΩ）
    return _make_args(
        items,
        commands="unit_upo1000x",
        profile="unit_upo1000x",
        probe="9530",
        sim_bandwidth=sim_bandwidth,
    )


def test_sim_upo1000x_runs_all_items(fast_mode):
    """无硬件端到端：优利德 UPO1000X 配置五项校准全部跑通且结果合理。"""
    _, _, _, all_results = run_calibration(_upo_args("all"))
    assert set(all_results) == {"amp", "dc_gain", "delta_time", "bandwidth", "transient"}
    for key in ("amp", "dc_gain", "delta_time"):
        errs = [abs(r["error"]) for r in all_results[key]]
        assert max(errs) < 1.0, f"{key} 误差异常: {errs}"
    bws = [r["bandwidth_mhz"] for r in all_results["bandwidth"]]
    assert all(90 <= bw <= 110 for bw in bws), f"带宽应接近 100MHz，实际 {bws}"
    row = all_results["transient"][0]
    assert row["risetime_ns"] > 0
    assert row["pos_overshoot"] >= 0, "该系列有正过冲测量，应给出数值"


def test_sim_upo1000x_dialect_is_parsed(fast_mode):
    """模拟器必须真正解析该方言：垂直挡位、测量源、采集模式、扫描模式与触发电平。"""
    inst_osc, _, _, _ = run_calibration(_upo_args("amp"))
    # 幅度点表最后一个挡位是 10 V/div，说明 :CHANnel<n>:SCALe 被解析
    assert inst_osc.vertical_scale["1"] == pytest.approx(10.0)
    assert inst_osc.meas_source == "CHANnel1"
    assert inst_osc.acq_mode == "AVERage"
    assert inst_osc.horizontal_scale == pytest.approx(1e-3)
    assert inst_osc.channel_on["1"] == "ON"

    inst_osc, _, _, _ = run_calibration(_upo_args("transient"))
    # 没有 :SINGle 命令，单次采集靠 :TRIGger:SWEep SINGle + :RUN
    assert inst_osc.stop_after == "SINGle"
    assert inst_osc.acquire_state == "RUN"
    assert inst_osc.trigger_level["global"] == pytest.approx(-0.5)
    assert inst_osc.horizontal_scale == pytest.approx(5e-9)  # 1MΩ 慢沿用 5 ns/div
