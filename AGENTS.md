# AGENTS.md

示波器自动校准 CLI（`osccal`）。注释、文档字符串、终端输出均为中文，新增代码保持一致。

## 环境与命令

- 使用仓库内 `.venv`（Python 3.12，已装好依赖与 dev 工具）。系统 `python` **没有** ruff/mypy/pytest，必须走 `.venv`。
- 未激活时直接用 `.venv/bin/<tool>`，或先 `source .venv/bin/activate`。
- 本地校验顺序（与 CI 一致，`.github/workflows/ci.yml`）：

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check osccal tests simulate_calibrate.py
.venv/bin/mypy
.venv/bin/pytest
```

- `mypy` 只检查 `pyproject.toml` 中列出的 4 个文件（`core/types.py`、`core/config.py`、`core/config_validation.py`、`core/scpi_trace.py`），不是全仓库；`ruff format` 不覆盖 `commands/ profiles/ calibrators/`。
- 单测：`.venv/bin/pytest tests/test_mdo3_commands.py::TestX::test_y`。
- 无硬件端到端：`.venv/bin/python simulate_calibrate.py`（默认快速模式，自动应答 prompt）。

## 架构

- 入口 `osccal/cli.py:main`（`pyproject.toml` 的 `[project.scripts]`）。`osccal/core/` 为通信/配置/存储/导出，`osccal/measure/` 为各校准项目，`registry.py` 定义执行顺序 amp→dc_gain→delta_time→bandwidth→transient。
- 配置驱动，新增示波器**只加 JSON 不改代码**：`commands/`（SCPI 命令模板）、`profiles/`（硬件特征/校准点）、`calibrators/`（校准仪与探头）。`--auto` 按 `manufacturer`/`models` 精确匹配，回退 `series`、文件名前缀。
- 配置结构校验只有一份实现 `osccal/core/config_validation.py`，运行时加载和 `tests/test_all_configs.py` 共用；改 JSON 契约时同步这里，不要另写校验。
- 测试用 `tests/conftest.py` 的 `FakeInstrument` 模拟 pyvisa，无需真实设备；`conftest.py` 会把仓库根注入 `sys.path`。

## 注意事项

- `data/*.json`、`data/*.xlsx` 被 gitignore（仅保留 `.gitkeep`），不要把生成物提交。
- 启动时强制 stdout/stderr 为 UTF-8（Windows 中文控制台/重定向的 `UnicodeEncodeError` 修复），改相关代码别破坏该行为。
- 已支持设备与各字段含义见 `README.md`（内容详尽，改动前先读）。
