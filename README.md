# OscCal-CLI

示波器自动校准命令行工具。通过 SCPI 指令控制 FLUKE 9500B 校准仪和示波器，自动完成示波器各项校准项目，生成校准结果和报告。

## 功能特性

- **6 项校准项目**：幅度（ΔV）、直流增益、Δt（时间）、频带宽度、上升时间及过冲、全项目校准
- **多品牌示波器**：泰克、普源、鼎阳、优利德、周立功，覆盖 9+ 系列
- **FLUKE 9500B 校准仪**：支持 9560、9550、9530 三种有源探头，自动匹配阻抗
- **智能阻抗管理**：根据探头型号和信号模式自动设置校准仪输出阻抗，不匹配时自动切换并警告
- **多种连接方式**：USB（VISA）、网线（TCPIP/Socket）、GPIB、串口（ASRL）
- **多通道校准**：支持多通道顺序校准，切换通道时等待用户确认接线
- **自适应垂直位置**：小电压挡位自动调整示波器垂直位置，确保波形完整显示
- **配置驱动扩展**：新增示波器只需添加 JSON 文件，无需修改代码
- **美观终端输出**：Rich 表格、进度条、超差红色高亮
- **Excel 报告导出**：含数据表、误差散点图、超差高亮
- **SCPI 通信重试**：瞬态错误自动重试（0.5s 间隔），避免偶发通信失败
- **单元测试**：pytest 测试套件覆盖指令集结构、Profile 校验、SCPI 通信集成
- **本地模拟运行**：内置模拟仪器脚本，无需真实设备即可跑通完整校准流程

## 环境要求

- Python >= 3.9
- VISA 运行时（如 [NI-VISA](https://www.ni.com/zh-cn/support/downloads/drivers/download.ni-visa.html)），用于 USB/GPIB/串口连接
- 网线连接无需 VISA 运行时

## 安装

```bash
git clone <repository-url>
cd OscCal-CLI
pip install -e .
```

安装完成后即可使用 `osccal` 命令。

## 快速开始

### 1. 查看可用设备

```bash
osccal device list
```

### 2. 执行校准（交互模式）

```bash
osccal calibrate
```

程序将引导你依次选择：
1. 校准仪配置文件
2. 校准仪探头型号
3. 示波器指令集文件
4. 示波器特征配置文件
5. 校准通道（支持多通道）
6. 校准仪 VISA 资源
7. 示波器 VISA 资源

多通道校准时，切换通道会暂停等待用户移动探头并确认接线。

校准完成后，数据自动保存到 `data/` 目录。

### 3. 查看校准结果

```bash
# 查看最近一次校准数据
osccal show --latest

# 查看指定文件
osccal show --file data/calibration_20260427_143000.json

# 交互选择文件
osccal show
```

### 4. 导出 Excel 报告

```bash
# 导出最近一次校准数据为 Excel
osccal export

# 指定输入和输出
osccal export --file data/calibration_20260427_143000.json --output report.xlsx
```

## 本地模拟运行

无需真实示波器和校准仪，即可在本地跑通完整校准流程，便于开发调试和演示。模拟脚本内置两个实现 pyvisa 接口的模拟仪器，通过共享状态对象传递信号：校准仪 `write` 更新输出信号，示波器 `query` 据此返回合理的测量值，并按一阶低通模型模拟示波器 -3dB 带宽滚降。

```bash
# 默认跑全部 5 项校准（MDO34、CH1、9560 探头、模拟带宽 200MHz）
python simulate_calibrate.py

# 指定校准项目
python simulate_calibrate.py --items amp,dc_gain

# 多通道 + 切换探头
python simulate_calibrate.py --channel 1,2 --probe 9530

# 打印完整 SCPI 指令日志并导出 JSON + Excel
python simulate_calibrate.py --log-scpi --export
```

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--commands` | 指令集文件名（不含 .json） | `tektronix_mdo3` |
| `--profile` | Profile 文件名（不含 .json） | `tektronix_mdo34` |
| `--calibrator` | 校准仪配置文件名（不含 .json） | `fluke_9500b` |
| `--items` | 校准项目，逗号分隔 | `all` |
| `--channel` | 通道，逗号分隔（如 1,2） | `1` |
| `--probe` | 探头型号（9560/9550/9530） | `9560` |
| `--bandwidth` | 起始带宽（MHz） | `100.0` |
| `--bd-step` | 带宽扫描步进（MHz） | `20.0` |
| `--sim-bandwidth` | 模拟示波器 -3dB 带宽（MHz） | `200.0` |
| `--log-scpi` | 打印完整 SCPI 指令序列 | 关闭 |
| `--export` | 保存 JSON 数据并导出 Excel | 关闭 |
| `--real-sleep` | 保留真实 sleep 延时（默认加速） | 关闭 |

默认启用快速模式（禁用 `time.sleep`、自动应答 `click.prompt`），全程秒级完成；多选项上升时间（如 9530 探头）会自动选择默认值。

## 命令详解

### `osccal calibrate`

执行示波器校准流程。

```bash
osccal calibrate [OPTIONS]
```

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--osc` | 示波器指令集配置文件路径 | 交互选择 |
| `--profile` | 示波器特征配置文件路径 | 交互选择 |
| `--calibrator` | 校准仪配置文件路径 | 交互选择 |
| `--channel` | 校准通道，逗号分隔（1,2,3,4） | 交互选择 |
| `--probe` | 校准仪探头型号（9560/9550/9530） | 交互选择 |
| `--items` | 校准项目，逗号分隔 | `all` |
| `--resource-osc` | 示波器 VISA 资源地址 | 交互选择 |
| `--resource-cal` | 校准仪 VISA 资源地址 | 交互选择 |
| `--socket-osc` | 示波器 Socket 地址（host:port） | — |

**校准项目名称**：

| 名称 | 项目 |
|------|------|
| `amp` | 幅度（ΔV） |
| `dc_gain` | 直流增益 |
| `delta_time` | Δt（时间） |
| `bandwidth` | 频带宽度 |
| `transient` | 上升时间及过冲 |
| `all` | 全部项目 |

**示例**：

```bash
# 交互模式，校准全部项目
osccal calibrate

# 指定配置和资源，校准通道2的幅度和直流增益
osccal calibrate \
  --osc commands/tektronix_mdo.json \
  --profile profiles/tektronix_mdo3000.json \
  --calibrator calibrators/fluke_9500b.json \
  --probe 9560 \
  --channel 2 \
  --items amp,dc_gain \
  --resource-cal "GPIB0::19::INSTR" \
  --resource-osc "GPIB0::10::INSTR"

# 多通道校准
osccal calibrate --channel 1,2,3,4

# 使用 Socket 连接示波器
osccal calibrate --socket-osc 192.168.1.100:5025
```

### `osccal show`

显示校准数据。

```bash
osccal show [OPTIONS]
```

| 选项 | 说明 |
|------|------|
| `--latest` | 显示最近一次校准数据 |
| `--file` | 指定校准数据文件路径 |

### `osccal export`

导出校准报告。

```bash
osccal export [OPTIONS]
```

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--format` | 导出格式（目前支持 `excel`） | `excel` |
| `--file` | 校准数据文件路径 | 最新文件 |
| `--output` | 输出文件路径 | 自动生成 |

### `osccal device list`

列出所有可用的 VISA 设备资源。

```bash
osccal device list
```

### `osccal device info`

查询设备的 `*IDN?` 标识信息。

```bash
osccal device info [OPTIONS]
```

| 选项 | 说明 |
|------|------|
| `--resource` | VISA 资源地址 |
| `--socket` | Socket 地址（host:port） |

## 项目结构

```
OscCal-CLI/
├── osccal/                          # 主程序包
│   ├── cli.py                       # CLI 命令入口
│   ├── core/                        # 核心模块
│   │   ├── config.py                # JSON 配置文件加载
│   │   ├── comm.py                  # SCPI 通信（PyVISA / Socket，含重试）
│   │   ├── connect.py               # 设备连接与 *IDN? 查询
│   │   ├── command.py               # SCPI 命令组装
│   │   ├── storage.py               # 校准数据 JSON 存储
│   │   ├── export.py                # Excel 报告导出
│   │   ├── table_configs.py         # 表格配置集中管理
│   │   └── utils.py                 # 共享工具函数
│   ├── measure/                     # 校准测量模块
│   │   ├── base.py                  # 校准基类（阻抗管理、垂直位置调整）
│   │   ├── amp.py                   # 幅度校准
│   │   ├── dc_gain.py               # 直流增益校准
│   │   ├── delta_time.py            # Δt 时间校准
│   │   ├── bandwidth.py             # 频带宽度校准
│   │   ├── transient.py             # 上升时间及过冲校准
│   │   ├── all.py                   # 全项目校准
│   │   └── registry.py              # 校准器映射与执行顺序
│   └── draw/                        # 绘图模块（matplotlib）
│       ├── amp.py
│       ├── dc_gain.py
│       ├── time.py
│       └── bandwidth.py
├── commands/                        # 示波器指令集配置
│   ├── tektronix_mdo.json           #   泰克 MDO3000/MDO4000
│   ├── tektronix_mdo3.json          #   泰克 3 Series MDO（MDO34/MDO32）
│   ├── tektronix_tbs.json           #   泰克 TBS2000B
│   ├── tektronix_tds.json           #   泰克 TDS5000
│   ├── rigol_mso.json               #   普源 MSO5000
│   ├── siglent_sds.json             #   鼎阳 SDS
│   ├── unit_utd.json                #   优利德 UTD2000CEX/UTD7000C
│   └── zlg_zds.json                 #   周立功 ZDS2000/ZDS4000
├── profiles/                        # 示波器特征配置
│   ├── tektronix_mdo3000.json
│   ├── tektronix_mdo34.json         #   泰克 MDO34（4 通道）
│   ├── tektronix_mdo32.json         #   泰克 MDO32（2 通道）
│   ├── tektronix_tbs2000b.json
│   ├── tektronix_tds5000.json
│   ├── rigol_mso5000.json
│   ├── siglent_sds.json
│   ├── unit_utd2000cex.json
│   ├── unit_utd7000c.json
│   ├── zlg_zds2000.json
│   └── zlg_zds4000.json
├── calibrators/                     # 校准仪配置
│   └── fluke_9500b.json             #   FLUKE 9500B（含探头 9560/9550/9530）
├── tests/                           # 单元测试（pytest）
│   ├── conftest.py                  # 共享 fixture 与 FakeInstrument
│   ├── test_mdo3_commands.py        # MDO3 指令集结构测试
│   ├── test_mdo3_profiles.py        # MDO3 Profile 校验测试
│   └── test_mdo3_comm_integration.py # SCPI 通信集成测试
├── data/                            # 校准数据存储目录
├── simulate_calibrate.py            # 本地模拟校准脚本
└── pyproject.toml                   # 项目配置
```

## 配置文件说明

配置文件采用 JSON 格式，分为三类，结构清晰便于人工阅读和编辑。

### 指令集文件（commands/）

定义示波器的 SCPI 命令模板，与设备型号（指令集）绑定。

```json
{
    "name": "Tektronix_MDO",
    "description": "Tektronix MDO/MSO/DPO series ...",
    "type": "pyvisa",
    "series": ["MDO4000C", "MDO3000", "..."],
    "feature": {
        "meas": "merge",
        "return_value_index": 1,
        "get_value": "Direct"
    },
    "keyword": {
        "imp_fif": "FIF",
        "imp_meg": "MEG",
        "meas_amp": "AMP",
        "meas_period": "PERI",
        "meas_max": "MAX",
        "meas_min": "MIN",
        "..."
    },
    "actions": {
        "preset": { "commands": ["FAC"], "args_num": 0, "..." },
        "set_channel": { "commands": ["SEL:CH", " "], "args_num": 2, "..." },
        "set_vertical_scale": { "commands": ["CH", ":SCALE "], "args_num": 2, "..." },
        "set_vertical_position": { "commands": ["CH", ":POS "], "args_num": 2, "..." },
        "..."
    }
}
```

关键字段：

| 字段 | 说明 |
|------|------|
| `type` | 通信方式：`pyvisa` 或 `socket` |
| `feature.meas` | 测量模式：`merge`（先设源+类型再读值）或 `split`（同时指定项目和通道） |
| `keyword` | SCPI 关键字映射（阻抗、测量类型、max/min 等） |
| `actions` | SCPI 命令模板，`commands` 为命令片段，`args_num` 为参数数量 |

### 特征文件（profiles/）

定义示波器的硬件特征和校准点，与校准规范绑定。

```json
{
    "name": "osc",
    "description": "Tektronix MDO3000 ...",
    "factor": "tektronix",
    "series": "MDO3000",
    "imp_has_50": true,
    "vertical_div": 8,
    "horizontal_div": 10,
    "bandwidth": 350E6,
    "bd_step": 30E6,
    "calibration_limits": {
        "amp": { "upper": 2.0, "lower": -2.0 },
        "dc_gain": { "upper": 2.0, "lower": -2.0 },
        "delta_time": { "upper": 2.0, "lower": -2.0 },
        "bandwidth": { "min_mhz": 100 },
        "transient": {}
    },
    "points": {
        "delta_amp": [0.001, 0.002, 0.005, "..."],
        "dc_gain": [0.001, 0.002, 0.005, "..."],
        "delta_time": [10E-9, 20E-9, 40E-9, "..."],
        "bandwidth": [0.005, 0.010, 0.020, "..."]
    }
}
```

关键字段：

| 字段 | 说明 |
|------|------|
| `imp_has_50` | 是否支持 50Ω 阻抗 |
| `vertical_div` | 垂直方向分度数 |
| `horizontal_div` | 水平方向分度数 |
| `bandwidth` | 标称带宽（Hz） |
| `bd_step` | 带宽扫描步进（Hz） |
| `calibration_limits` | 各校准项目的允差限 |
| `points` | 各校准项目的校准点列表 |

### 校准仪文件（calibrators/）

定义校准仪的 SCPI 命令、探头信息和阻抗规则。

```json
{
    "name": "9500B",
    "description": "Fluke 9500B Oscilloscope Calibrator ...",
    "type": "pyvisa",
    "keyword": {
        "imp_fif": "50",
        "imp_meg": "10000"
    },
    "probes": {
        "9560": { "name": "9560", "max_frequency": "6.4 GHz", "edge_rise_times": [70E-12] },
        "9550": { "name": "9550", "description": "Fast Edge Head", "edge_rise_times": [25E-12] },
        "9530": { "name": "9530", "max_frequency": "600 MHz", "edge_rise_times": [150E-12, 500E-12] }
    },
    "impedance_rules": {
        "9560": { "DC": ["1M","50"], "SQU": ["1M","50"], "MARK": ["50"], "SIN": ["50"], "EDGE": ["50"] },
        "9550": { "EDGE": ["50"] },
        "9530": { "DC": ["1M","50"], "SQU": ["1M","50"], "MARK": ["1M","50"], "SIN": ["1M","50"], "EDGE": ["1M","50"] }
    },
    "actions": { "..." }
}
```

关键字段：

| 字段 | 说明 |
|------|------|
| `probes` | 探头信息，`edge_rise_times` 为可用的上升时间列表（秒），`max_frequency` 为最大正弦波频率 |
| `impedance_rules` | 阻抗规则，按探头型号和信号模式定义支持的阻抗列表。`["1M","50"]` 表示两种都支持，`["50"]` 表示仅支持 50Ω |

## 探头阻抗规则

校准仪输出阻抗由探头型号和信号模式共同决定，程序自动匹配：

| 探头 | DC | SQU | MARK | SIN | EDGE |
|------|-----|------|------|------|------|
| **9560** | 1MΩ / 50Ω | 1MΩ / 50Ω | 仅 50Ω | 仅 50Ω | 仅 50Ω |
| **9550** | — | — | — | — | 仅 50Ω |
| **9530** | 1MΩ / 50Ω | 1MΩ / 50Ω | 1MΩ / 50Ω | 1MΩ / 50Ω | 1MΩ / 50Ω |

**自动切换逻辑**：

- 示波器支持 50Ω 时，优先按示波器当前阻抗设置校准仪
- 探头不支持期望阻抗时（如 9560 在 MARK 模式下不支持 1MΩ），自动切换为探头支持的阻抗，同时设置示波器和校准仪，并打印黄色警告
- 示波器不支持 50Ω 但探头只能输出 50Ω 时，打印红色警告提示阻抗不匹配

## 探头上升时间

EDGE 校准时，校准仪上升时间根据探头型号自动设置：

| 探头 | 可选上升时间 |
|------|------------|
| **9560** | 70 ps |
| **9550** | 25 ps |
| **9530** | 150 ps / 500 ps（交互选择） |

## 添加新示波器

只需创建两个 JSON 文件，无需修改任何代码：

### 1. 创建指令集文件

在 `commands/` 目录下新建 JSON 文件，定义示波器的 SCPI 命令模板。可参考已有文件（如 `commands/tektronix_mdo.json`）的格式。

### 2. 创建特征文件

在 `profiles/` 目录下新建 JSON 文件，定义示波器的硬件参数和校准点。可参考已有文件（如 `profiles/tektronix_mdo3000.json`）的格式。

完成后运行 `osccal calibrate`，程序会自动发现新配置文件。

## 校准项目说明

### 幅度（ΔV）

校准垂直偏转系数幅度准确度。校准仪输出方波信号（SQU），示波器测量幅度值，计算相对误差：

```
误差(%) = (测量值 - 标准值) / 标准值 × 100%
```

小电压挡位（≤2mV/div）时自动调整垂直位置，确保波形完整显示。

### 直流增益

校准直流增益准确度。校准仪输出直流信号（DC），分别测量正负偏移的均值，计算增益误差：

```
G = (Ur+ - Ur-) / (U+ - U-)
误差(%) = (1 - G) / G × 100%
```

支持 1MΩ 和 50Ω 两种阻抗（若示波器支持）。

### Δt（时间）

校准水平偏转系数时间准确度。校准仪输出梳状波（MARK）信号，示波器测量周期，计算相对误差。

有 50Ω 阻抗的示波器按 50Ω 设置校准，只有 1MΩ 的示波器按 1MΩ 设置。

### 频带宽度

校准示波器频带宽度。校准仪输出正弦波信号（SIN），逐步增加频率，当幅度降至参考幅度的 0.707 倍（-3dB 点）时，记录当前频率为带宽。

### 上升时间及过冲

校准瞬态响应。校准仪输出快沿信号（EDGE），示波器单次采集，测量上升时间和正过冲。上升时间根据探头型号自动设置。

## 已支持的示波器

| 品牌 | 系列 | 指令集文件 | 特征文件 | 连接方式 |
|------|------|-----------|---------|---------|
| 泰克 | MDO3000, MDO4000, MSO4000B, DPO4000B | `tektronix_mdo.json` | `tektronix_mdo3000.json` | VISA |
| 泰克 | MDO34（4 通道） | `tektronix_mdo3.json` | `tektronix_mdo34.json` | VISA |
| 泰克 | MDO32（2 通道） | `tektronix_mdo3.json` | `tektronix_mdo32.json` | VISA |
| 泰克 | TBS2000B | `tektronix_tbs.json` | `tektronix_tbs2000b.json` | VISA |
| 泰克 | TDS5000 | `tektronix_tds.json` | `tektronix_tds5000.json` | VISA |
| 普源 | MSO5000 | `rigol_mso.json` | `rigol_mso5000.json` | VISA |
| 鼎阳 | SDS6000 PRO, SDS6000A | `siglent_sds.json` | `siglent_sds.json` | VISA |
| 优利德 | UTD2000CEX | `unit_utd.json` | `unit_utd2000cex.json` | VISA |
| 优利德 | UTD7000C | `unit_utd.json` | `unit_utd7000c.json` | VISA |
| 周立功 | ZDS2000/2000B | `zlg_zds.json` | `zlg_zds2000.json` | Socket |
| 周立功 | ZDS4000/3000 | `zlg_zds.json` | `zlg_zds4000.json` | Socket |

## 测试

项目使用 pytest 进行单元测试，覆盖指令集结构、Profile 校验和 SCPI 通信集成。

```bash
# 运行全部测试
pytest

# 运行指定测试文件
pytest tests/test_mdo3_commands.py

# 查看详细输出
pytest -v
```

测试内容：

| 测试文件 | 覆盖范围 |
|---------|---------|
| `tests/test_mdo3_commands.py` | MDO3 指令集结构完整性、action/keyword 齐全性、SCPI 组装与手册一致性 |
| `tests/test_mdo3_profiles.py` | MDO34/MDO32 Profile 参数校验（通道数、带宽、校准点、限值） |
| `tests/test_mdo3_comm_integration.py` | `scpi_write`/`scpi_query`/`read_measurement`/`setup_impedance` 通信链路 |

## 依赖

| 库 | 用途 |
|---|---|
| [click](https://click.palletsprojects.com/) | CLI 命令框架 |
| [rich](https://rich.readthedocs.io/) | 终端美观输出 |
| [PyVISA](https://pyvisa.readthedocs.io/) | VISA 仪器通信 |
| [PyVISA-py](https://pyvisa-py.readthedocs.io/) | PyVISA 纯 Python 后端 |
| [openpyxl](https://openpyxl.readthedocs.io/) | Excel 报告生成 |
| [matplotlib](https://matplotlib.org/) | 数据绘图 |

开发依赖（测试）：

| 库 | 用途 |
|---|---|
| [pytest](https://docs.pytest.org/) | 单元测试框架 |

## License

MIT
