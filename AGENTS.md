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
.venv\Scripts\ruff format --check osccal tests
.venv\Scripts\mypy
.venv\Scripts\pytest
```

- `mypy` 只检查 `pyproject.toml` 中列出的 4 个文件（`core/types.py`、`core/config.py`、`core/config_validation.py`、`core/scpi_trace.py`），不是全仓库；`ruff format` 不覆盖 `commands/ characteristics/ specs/ schemes/ calibrators/`。
- 单测：`.venv\Scripts\pytest tests/test_mdo3_commands.py::TestX::test_y`。
- 无硬件核对：`osccal plan`（离线解析点表，不连接仪器）。v0.2.0 不再提供模拟仪器脚本（旧 `simulate_calibrate.py` 已删除）。
- 基线：`.venv\Scripts\pytest` 应全绿（用例数随功能增长，不在此写死）。

## 架构

- 入口 `osccal/cli.py:main`（`pyproject.toml` 的 `[project.scripts]`）。`osccal/core/` 为通信/配置/存储/导出/取点解析，`osccal/measure/` 存放 10 个校准项目实现，`registry.py` 定义项目清单与执行顺序。
- 配置驱动，新增示波器**只加 JSON 不改代码**：`commands/`（SCPI 命令模板与能力声明）、`characteristics/`（纯硬件特征：通道数、格线、档位集合、标称带宽、最高采样率）、`calibrators/`（校准仪输出能力与探头）。`--auto` 按 `manufacturer`/`models` 精确匹配，回退 `series`、文件名前缀。`commands/` 只保留 `tektronix_mdo.json`（MDO3052/3032 使用）与 `tektronix_mdo3.json`（3 Series MDO 方言，暂无特征文件）。
- v0.3.0 起 `characteristics/` 提供 `tektronix_mdo3052.json`（500 MHz）与 `tektronix_mdo3032.json`（350 MHz）两份，其余机型待实机验证后按新契约重建，不提供历史 Profile。
- **v0.3.0 配置分层（不兼容 v0.2.x）**：`characteristics/` 只写硬件事实；`specs/` 只写规范要求（条款、记录表、公式、`reference_limits`、偏离）；`schemes/` 写本轮方案（项目 `methods` 候选集、`method` 实际执行方法、`primary`、`points`、`stimulus`、人工确认提示）。`cli.py` 用 `--scheme`（默认 `jjf1057_2026_single`，试验方案为 `jjf1057_2026`）与 `--characteristics` 指定，记录分别写 `metadata.scheme` / `metadata.spec` / `metadata.characteristics_file`。旧 `--profile`/`--spec` 与旧 JSON 布局不再兼容，加载时明确报错。
- `osccal/core/methods.py` 是方法键、中文名、短标签与 `PRIMARY_METHODS`/`NO_PRIMARY_METHODS` 的唯一来源；方案校验（`validate_scheme`）、计划表与 runner 的 `method_enabled()` 共用它。**方案里只能写已实现的方法**，未实现的方法（如随机噪声 RMS 读数法）加载即报错。
- **v0.2.0（不兼容 V0.1.0）**：`osccal/measure/registry.py` 是唯一项目清单（JJF 1057-2026 的 10 项，旧项目已删除、无别名），`RUNNERS` **已全部落地**；`osccal/core/points.py` 是唯一取点实现（6 种策略，超出标准器能力的点写入 `skipped` 并说明原因，**禁止静默降级**）；`osccal plan` 是离线核对入口，不连接仪器。实机验证结论见 `verification/jjf1057_2026.json`（状态：verified / verified_with_caveat / deviation）。
- **实机教训（M7' 硬件验证得出，改测量代码前先看这一节）**：
  - **读数前必须重新采集**：单次采集完成后示波器停止，改完激励/时基若不再采集，`MEASU:IMM:VAL?` 返回上一点的读数。`base._read_meas` 已统一先触发一次单次采集并用 `ACQuire:STATE?` 轮询确认结束。
  - **直流/无沿信号不要走单次采集**：等不到触发会白等 5 s 超时。用 `_read_meas(trigger=False)` / `_ensure_free_running()`。
  - **读数要等收敛**：标准源换函数后幅度约需 2 s 建立（0.5 s 只到 3%、1.0 s 到 49%）。统一用 `_read_meas_stable()`（间隔 0.5 s 连读、相对差 ≤0.1%、最长 6 s），并把等待与残差写入记录。
  - **记录长度必须等于分析点数，且在采集之前固定**：实测 100 µs/div 下记录 1000 点拟合正确（3000.6 Hz），记录 10000 点则偏差 4.8 倍（数据与 `WFMOutpre:XINcr` 不匹配）。ENOB 在设置时基前固定 `HOR:RECORDLENGTH`；时基拟合法也必须在采集前固定，先采集再改会让波形与新 `XINcr` 不匹配。
  - **水平挡位序列随记录长度变化**：记录 10000 点时 800 ns/div 可用、1 µs 不可用；记录 1000 点时相反。挡位表不能写死，`_set_timebase` 已回读实际值并写入记录。
  - **阻抗必须两端一起设并回读校验**：50 Ω 输出接 1 MΩ 输入会让读数翻倍（0.5 Vpp 读成 1.004 V），1 MΩ 接 50 Ω 则降为 0.66 倍。`_apply_impedance` 已含 `_verify_impedance`，这类错误不产生 SCPI 错误码。
  - **测量顺序会影响结果**：先跑直流类方法再测方波幅度，方波法会系统性偏高 1.9%~5.0%（量化台阶整数倍）。直流增益把方波方法排在最前面。
  - **示波器平均测量带偏置补偿**：直流偏置不能用 MEAN 读数，必须取**原始码值** `(码值 − YOFf) × YMUlt`（不叠加 YZEro），否则拟合截距恒接近 0。
  - **9500B 的 DC 输出不能设 0 V**：`SOUR:VOLT 0` 与 0.5 mV 都被静默丢弃、保持原值（最小可设约 1 mV）。零点改用 ±1 mV 两点插值。
  - **快沿/脉冲测量要多次采集平均**：单次重复性约 ±52 ps，10 次平均降到约 ±17 ps。
  - **无效读数要重新采集，而不是重复查询**：泰克用 `9.9E+37`、优利德用 `*`、ZDS 用 `3.4E+38` 表示"本次测量无效"。`read_measurement` 内部的重试只重发测量设置，同一份无效采集不会变；`base._read_meas` 现在会在 `InvalidMeasurementError` 时重新采集（最多 3 次）。实机现象：每次会话的第一条读数偶发 `9.9E+37`，不重采会直接让整项失败。
- 版本号只有一处来源：`osccal/__init__.py:__version__`。`pyproject.toml` 用 `dynamic = ["version"]` + `[tool.setuptools.dynamic]` 指向它，CLI 用 `@click.version_option(version=__version__)`。**不要在任何地方再写死版本字符串**（`tests/test_specs.py` 守护）。
- 配置文件一律 JSON，不引入 YAML：各类配置共用同一套校验与 `configuration_snapshot` 追溯链（快照基于 `json.dumps`，换 YAML 会破坏 sha256 语义）。
- 配置结构校验只有一份实现 `osccal/core/config_validation.py`，运行时加载和 `tests/test_all_configs.py` 共用；改 JSON 契约时同步这里，不要另写校验。`REQUIRED_KEYWORDS` 之外的测量 keyword 可省略，表示机型没有该能力（旧 `transient.py` 已删除，新项目按需检查 `cmd_osc["keyword"]` 是否存在对应键，不要用"缺少 action"让整项失败）。
- 结果表格的列与**显示精度**只有一份声明 `osccal/core/table_configs.py`（`ITEM_CONFIGS`/`EXCEL_ITEM_CONFIGS` 的 `precision` 指向 `ITEM_PRECISION`）：终端 `show` 与 Excel 导出共用 `osccal/core/utils.py` 的 `format_display_value`/`prepare_excel_value`，增删列时同步精度规格（列数一致性由 M6' 重写后的导出测试守护）。`active_config()` 按记录行的 `methods_selected` / 方案 `method` 删除未选方法列，`method_note()` 生成表下“执行方法”；频响/ENOB 表含 `vertical_scale`（挡位 V/div）。Excel 单元格按显示精度舍入，超差判定仍用未舍入原值，未舍入读数只保留在 JSON 记录里。参考指标文本由 `table_configs.reference_text(name, metadata["limits"])` 从规范 `reference_limits` 渲染，旧记录无 limits 时回退静态文本；`reference_limits` 是唯一来源，不要在报告代码里另写一份限值。
- 时基误差的 7.9.1（频率法）与 7.9.2（拟合法）是规范的**并列方法**：记录与报告两列都出，不指定唯一判定值；拟合值仅在"拟合频率与读数相差 ≤5%"时有效，否则置空并在 `fit_note` 说明。
- 幅度口径的旧规则（`meas_amp_scale`、`_nudge_trigger_level` 的具体用法）描述的是 V0.1.0 测量层，相关模块已在 M1' 删除；`_nudge_trigger_level` 仍用于换挡后复位平均。`measure/base.py` 的公共能力（连接、SCPI 追踪、读数收敛、单次采集、波形读回、阻抗回读、表格）供各 runner 复用；重写新项目时**以 JJF 1057-2026 条款为准，不要沿用旧口径**。
- 方法选择：方案 `methods` 是候选集，`method` 指定实际执行的一种（与 `primary` 互斥）；runner 用 `method_enabled()` 判断，未选方法不发送采集指令、记录字段为 `null`。没有 `method` 时执行 `methods` 全部，`dc_gain`/`dc_offset` 用 `primary` 决定报告主记录值，`timebase_error` 两法并列、禁止 `primary`。默认方案是单方法方案，改动时必须同时守护试验方案与单方法方案的指令序列测试。
- 执行前校验：`cli.py` 在连接设备后、任何设置指令之前调用 `validate_device_identity()`（厂商与型号）并检查示波器/校准仪不是同一资源；不通过则本轮中止、不发任何设置指令，退出码 `2`。通道、项目、点表在解析阶段校验（`--scheme` 默认 `jjf1057_2026_single`，方案点表为空或项目不在方案中直接退出码 `2`）。
- 设备身份匹配：存在 `models` 时按精确白名单（忽略大小写与非字母数字字符，真机存在 `TBS 1102` 这类带空格上报）；校准仪无 `models` 时回退 `series`/`name` 的**型号家族**匹配（完全相同，或较短者为较长者前缀且长度 ≥ 4，如 `9500` 与 `9500B`）。`calibrators/*.json` 可用 `models` 声明同一型号的多种 `*IDN?` 上报形式。归一化规则只有一份实现 `config_validation.normalize_token`，`auto_detect.py` 的 `--auto` 识别与执行前校验共用它，改规则时两处同时生效。
- 测试用 `tests/conftest.py` 的 `FakeInstrument` 模拟 pyvisa，无需真实设备；`conftest.py` 会把仓库根注入 `sys.path`。

## 注意事项

- `data/*.json`、`data/*.xlsx` 被 gitignore（仅保留 `.gitkeep`），不要把生成物提交。
- 启动时强制 stdout/stderr 为 UTF-8（Windows 中文控制台/重定向的 `UnicodeEncodeError` 修复），改相关代码别破坏该行为。
- 校准记录 `metadata` 的状态字段（`status`/`item_status`/`failures`/`configurations`/`scheme`/`spec`/`scpi_errors`/`skipped_points`）与中断续存行为见 `README.md`，由 `tests/test_storage.py` 守护。
- 单项失败不终止整轮：`measure/all.py:run_items` 捕获项目异常后写 `failures`/`item_status` 并继续执行后续项目（`show`/Excel 跳过失败项目的部分数据）；只有用户中断与 `OutputShutdownError` 会终止会话。记录中的 NaN/Inf 由 `core/storage.py:_sanitize_nonfinite` 降级为 `null`，否则 `allow_nan=False` 会让整份记录写不进去。
- 受限沙箱环境下运行 `pytest` 时，使用 `tmp_path` 的用例可能因临时目录权限报 fixture setup 的 `PermissionError`；那是环境限制而非代码问题（正常终端不受影响）。
- 无效测量值的处理集中在 `core/comm.py`：`read_measurement` 识别 `*` 与 9.9E+37 / 3.4E+38 等无效哨兵并按设置重试，仍无效抛 `InvalidMeasurementError`；`base._read_meas` 收到该异常会**重新采集**后再读（最多 3 次）。不要在调用方再写浮点解析兜底。
- 个别机型**背靠背连续写入会静默丢指令**（UPO1104X 实测，错误队列仍报 `No error`）：指令集用 `feature.write_delay_ms` 声明写入间隔，`BaseCalibrator.__init__` 会调用 `comm.set_write_delay` 生效；未声明该字段的机型时序完全不变。排查"某条设置没生效"类问题时优先怀疑这一点。
- 已支持设备与各字段含义见 `README.md`（内容详尽，改动前先读）。
