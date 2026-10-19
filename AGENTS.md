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
- 无硬件核对：`osccal plan`（离线解析点表，不连接仪器）。`simulate_calibrate.py` 依赖校准流程，重建期 `RUNNERS` 为空时不可用，随 M3' 恢复。
- 基线：`.venv\Scripts\pytest` 应全绿（用例数随功能增长，不在此写死）。

## 架构

- 入口 `osccal/cli.py:main`（`pyproject.toml` 的 `[project.scripts]`）。`osccal/core/` 为通信/配置/存储/导出/取点解析，`osccal/measure/` 存放校准项目实现（v0.2.0 重建期为空），`registry.py` 定义项目清单与执行顺序。
- 配置驱动，新增示波器**只加 JSON 不改代码**：`commands/`（SCPI 命令模板与能力声明）、`profiles/`（硬件事实：通道数、格线、档位集合、标称带宽，**不再含校准点与限值**）、`calibrators/`（校准仪输出能力与探头）。`--auto` 按 `manufacturer`/`models` 精确匹配，回退 `series`、文件名前缀。
- v0.2.0 起 `profiles/` 只保留 MDO3052 一份；其余机型待实机验证后按新契约重建，不提供历史 Profile。
- `specs/`（v0.2.0 新增）声明**校准规范口径**：条款号、取点策略 `points.strategy`、屏占比/比值等参数、原始记录表号、偏离声明、参考指标。它只写"规范要求什么"，硬件能力仍取 `profiles/`、标准器输出能力取 `calibrators/output_limits`。校验实现在 `config_validation.validate_spec`，CLI 用 `--spec` 指定，记录写入 `metadata.spec`（含 sha256、deviations）。**v0.2.0 起规范是唯一口径，不保留"只记录不生效"的兼容状态。**
- **v0.2.0 重建中（不兼容 V0.1.0）**：`osccal/measure/registry.py` 是唯一项目清单（JJF 1057-2026 的 10 项，旧项目已删除、无别名），`RUNNERS` 在 M3'~M5' 逐个填充；`osccal/core/points.py` 是唯一取点实现（8 种策略，超出标准器能力的点写入 `skipped` 并说明原因，**禁止静默降级**）；`osccal plan` 是离线核对入口，不连接仪器。`RUNNERS` 为空期间 `osccal calibrate` 直接拒绝执行。
- 版本号只有一处来源：`osccal/__init__.py:__version__`。`pyproject.toml` 用 `dynamic = ["version"]` + `[tool.setuptools.dynamic]` 指向它，CLI 用 `@click.version_option(version=__version__)`。**不要在任何地方再写死版本字符串**（`tests/test_specs.py` 守护）。
- 配置文件一律 JSON，不引入 YAML：各类配置共用同一套校验与 `configuration_snapshot` 追溯链（快照基于 `json.dumps`，换 YAML 会破坏 sha256 语义）。
- 配置结构校验只有一份实现 `osccal/core/config_validation.py`，运行时加载和 `tests/test_all_configs.py` 共用；改 JSON 契约时同步这里，不要另写校验。`REQUIRED_KEYWORDS` 之外的测量 keyword 可省略，表示机型没有该能力（旧 `transient.py` 已删除，新项目按需检查 `cmd_osc["keyword"]` 是否存在对应键，不要用"缺少 action"让整项失败）。
- 结果表格的列与**显示精度**只有一份声明 `osccal/core/table_configs.py`（`ITEM_CONFIGS`/`EXCEL_ITEM_CONFIGS` 的 `precision` 指向 `ITEM_PRECISION`）：终端 `show` 与 Excel 导出共用 `osccal/core/utils.py` 的 `format_display_value`/`prepare_excel_value`，增删列时同步精度规格（列数一致性由 M6' 重写后的导出测试守护）。Excel 单元格按显示精度舍入，超差判定仍用未舍入原值，未舍入读数只保留在 JSON 记录里。
- 幅度口径与平均次数的旧规则（`meas_amp_scale`、`averages`、`_nudge_trigger_level` 的具体用法）描述的是 V0.1.0 测量层，相关模块已在 M1' 删除。`measure/base.py` 的公共能力（连接、SCPI 追踪、垂直位置防呆、触发微调）保留供 M3'~M5' 复用；重写新项目时**以 JJF 1057-2026 条款为准，不要沿用旧口径**。
- 同一模块提供**执行前校验**：`cli.py` 在连接设备后、任何设置指令之前调用 `validate_selection()`（通道/项目/探头信号与阻抗/带宽参数/必需 action）与 `validate_device_identity()`（厂商与型号）；不通过则本轮中止、不发任何设置指令，退出码 `2`。
- 设备身份匹配：存在 `models` 时按精确白名单（忽略大小写与非字母数字字符，真机存在 `TBS 1102` 这类带空格上报）；校准仪无 `models` 时回退 `series`/`name` 的**型号家族**匹配（完全相同，或较短者为较长者前缀且长度 ≥ 4，如 `9500` 与 `9500B`）。`calibrators/*.json` 可用 `models` 声明同一型号的多种 `*IDN?` 上报形式。归一化规则只有一份实现 `config_validation.normalize_token`，`auto_detect.py` 的 `--auto` 识别与执行前校验共用它，改规则时两处同时生效。
- 测试用 `tests/conftest.py` 的 `FakeInstrument` 模拟 pyvisa，无需真实设备；`conftest.py` 会把仓库根注入 `sys.path`。

## 注意事项

- `data/*.json`、`data/*.xlsx` 被 gitignore（仅保留 `.gitkeep`），不要把生成物提交。
- 启动时强制 stdout/stderr 为 UTF-8（Windows 中文控制台/重定向的 `UnicodeEncodeError` 修复），改相关代码别破坏该行为。
- 校准记录 `metadata` 的状态字段（`status`/`item_status`/`failures`/`configurations`/`scpi_errors`）与中断续存行为见 `README.md`，由 `tests/test_storage.py` 守护（CLI 流程测试随 M3' 重建）。
- 受限沙箱环境下运行 `pytest` 时，使用 `tmp_path` 的用例可能因临时目录权限报 fixture setup 的 `PermissionError`；那是环境限制而非代码问题（正常终端不受影响）。
- 无效测量值的处理集中在 `core/comm.py`：`read_measurement` 识别手册规定的无效标记 `*`（优利德 UPO1000X："返回数据为无效数据均用\*表示"）并重试，仍无效才抛出指明测量项的错误——不要在调用方再写浮点解析兜底。
- 个别机型**背靠背连续写入会静默丢指令**（UPO1104X 实测，错误队列仍报 `No error`）：指令集用 `feature.write_delay_ms` 声明写入间隔，`BaseCalibrator.__init__` 会调用 `comm.set_write_delay` 生效；未声明该字段的机型时序完全不变。排查"某条设置没生效"类问题时优先怀疑这一点。
- `measure/base.py:_adjust_vertical_position` 有防呆：波形远超整屏时判定为挡位问题并跳过调整。历史事故是按超屏量算出 −45.6 V 偏移、把波形推出屏幕，导致后续测量全部返回无效值——不要去掉该判断。
- 已支持设备与各字段含义见 `README.md`（内容详尽，改动前先读）。
