# AGENTS.md

示波器自动校准 CLI（`osccal`）。注释、文档字符串、终端输出均为中文，新增代码保持一致。

## 环境与命令

- 校验与运行一律走仓库内 `.venv`：项目依赖与 dev 工具（pytest/ruff/mypy）都装在这里，
  且与 CI 执行同一组检查；系统 `python` 可能装的是另一套版本的工具，用它跑校验会出现
  "本地通过、CI 失败"的假象。
- 版本不要在本文件写死：以 `pyproject.toml`（`requires-python`、`dependencies`、
  `[project.optional-dependencies].dev`）为准，需要时现场查
  （`.venv\Scripts\python --version`、`.venv\Scripts\python -m pip list`）。
- 工具路径：Windows（本机）`.venv\Scripts\<tool>`，激活 `.venv\Scripts\Activate.ps1`；
  POSIX 把 `Scripts` 换成 `bin`（`.venv/bin/<tool>`、`source .venv/bin/activate`）。
- 本地校验顺序（校验项与顺序同 CI；CI 在 Ubuntu 上把 `.[dev]` 装进 runner 的 Python，
  不使用仓库 `.venv`）：

```bash
.venv\Scripts\ruff check .
.venv\Scripts\ruff format --check osccal tests simulate_calibrate.py
.venv\Scripts\mypy
.venv\Scripts\pytest
```

- `mypy` 只检查 `pyproject.toml` 中列出的 4 个文件（`core/types.py`、`core/config.py`、`core/config_validation.py`、`core/scpi_trace.py`），不是全仓库；`ruff format` 不覆盖 `commands/ profiles/ calibrators/`。
- 单测：`.venv\Scripts\pytest tests/test_mdo3_commands.py::TestX::test_y`。
- 无硬件端到端：`.venv\Scripts\python simulate_calibrate.py`（默认快速模式，自动应答 prompt）。
- 基线：`.venv\Scripts\pytest` 应全绿（用例数随功能增长，不在此写死）。

## 架构

- 入口 `osccal/cli.py:main`（`pyproject.toml` 的 `[project.scripts]`）。`osccal/core/` 为通信/配置/存储/导出，`osccal/measure/` 为各校准项目，`registry.py` 定义执行顺序 amp→dc_gain→delta_time→bandwidth→transient。
- 配置驱动，新增示波器**只加 JSON 不改代码**：`commands/`（SCPI 命令模板）、`profiles/`（硬件特征/校准点）、`calibrators/`（校准仪与探头）。`--auto` 按 `manufacturer`/`models` 精确匹配，回退 `series`、文件名前缀。
- 配置结构校验只有一份实现 `osccal/core/config_validation.py`，运行时加载和 `tests/test_all_configs.py` 共用；改 JSON 契约时同步这里，不要另写校验。`REQUIRED_KEYWORDS` 之外的测量 keyword 可省略，表示机型没有该能力：省略 `meas_pos_overshoot` 时瞬态项目只测上升时间、过冲列记"不适用"（JSON 存 `null`，终端/Excel 由 `utils.NOT_APPLICABLE` 渲染），`transient.py` 用 `"meas_pos_overshoot" in cmd_osc["keyword"]` 判断；不要用"缺少 action"让整项失败。
- 结果表格的列与**显示精度**只有一份声明 `osccal/core/table_configs.py`（`ITEM_CONFIGS`/`EXCEL_ITEM_CONFIGS` 的 `precision` 指向 `ITEM_PRECISION`）：终端 `show` 与 Excel 导出共用 `osccal/core/utils.py` 的 `format_display_value`/`prepare_excel_value`，增删列时同步精度规格（`tests/test_export_precision.py` 守护列数一致性）。Excel 单元格按显示精度舍入，超差判定仍用未舍入原值，未舍入读数只保留在 JSON 记录里。
- 幅度测量口径由指令集的 `feature.meas_amp_scale` 声明（默认 1 = 标准值的 6 格峰峰值口径）；`meas_amp` 用有效值类测量（`CRMs`，无 `Amplitude` 的机型）时填 2，`amp.py` 经 `base._get_meas_amp_scale()` 换算，`bandwidth` 用比值故不换算。**不要退回 `PK2pk`**：方波沿的确定性峰化/过冲会被 max−min 全额计入（TBS1102 实测偏高 1.3~5.3%，加平均无效）。
- 平均次数由 Profile 的 `averages` 声明（默认 16），`amp`/`dc_gain`/`bandwidth` 经 `base._get_measurement_averages()` 读取；`base._nudge_trigger_level(scale)` 在换挡位后按 0.1 格、符号交替微调触发电平，迫使平均序列重启（手册 `ACQuire:NUMACq?`：Average 模式下改变触发参数会复位平均，Sample/PeakDetect 模式除外）。改动这些时序/数值前不要动各处 `time.sleep`（校准仪与示波器时序不能变）。
- 同一模块提供**执行前校验**：`cli.py` 在连接设备后、任何设置指令之前调用 `validate_selection()`（通道/项目/探头信号与阻抗/带宽参数/必需 action）与 `validate_device_identity()`（厂商与型号）；不通过则本轮中止、不发任何设置指令，退出码 `2`。
- 设备身份匹配：存在 `models` 时按精确白名单（忽略大小写与非字母数字字符，真机存在 `TBS 1102` 这类带空格上报）；校准仪无 `models` 时回退 `series`/`name` 的**型号家族**匹配（完全相同，或较短者为较长者前缀且长度 ≥ 4，如 `9500` 与 `9500B`）。`calibrators/*.json` 可用 `models` 声明同一型号的多种 `*IDN?` 上报形式。归一化规则只有一份实现 `config_validation.normalize_token`，`auto_detect.py` 的 `--auto` 识别与执行前校验共用它，改规则时两处同时生效。
- 测试用 `tests/conftest.py` 的 `FakeInstrument` 模拟 pyvisa，无需真实设备；`conftest.py` 会把仓库根注入 `sys.path`。

## 注意事项

- `data/*.json`、`data/*.xlsx` 被 gitignore（仅保留 `.gitkeep`），不要把生成物提交。
- 启动时强制 stdout/stderr 为 UTF-8（Windows 中文控制台/重定向的 `UnicodeEncodeError` 修复），改相关代码别破坏该行为。
- 校准记录 `metadata` 的状态字段（`status`/`item_status`/`failures`/`configurations`/`scpi_errors`）与中断续存行为见 `README.md`，由 `tests/test_storage.py`、`tests/test_cli_flow.py` 守护。
- 受限沙箱环境下运行 `pytest` 时，使用 `tmp_path` 的用例可能因临时目录权限报 fixture setup 的 `PermissionError`；那是环境限制而非代码问题（正常终端不受影响）。
- 已支持设备与各字段含义见 `README.md`（内容详尽，改动前先读）。
