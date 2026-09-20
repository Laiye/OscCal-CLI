# OscCal-CLI

示波器自动校准命令行工具。通过 SCPI 指令控制 FLUKE 9500B 校准仪和示波器，自动完成示波器各项校准项目，生成校准结果和报告。

## 功能特性

- **6 项校准项目**：幅度（ΔV）、直流增益、Δt（时间）、频带宽度、上升时间及过冲、全项目校准
- **多品牌示波器**：泰克、普源、鼎阳、优利德、周立功，覆盖 10+ 系列
- **FLUKE 9500B 校准仪**：支持 9560、9550、9530 三种有源探头，自动匹配阻抗
- **一键自动识别**：`--auto` 模式扫描 VISA 资源，自动匹配设备、指令集、特征配置、探头型号
- **智能阻抗管理**：根据探头型号和信号模式自动设置校准仪输出阻抗，不匹配时自动切换并警告
- **多种连接方式**：USB（VISA）、网线（TCPIP/Socket）、GPIB、串口（ASRL）
- **多通道校准**：支持多通道顺序校准，切换通道时等待用户确认接线
- **循环校准**：一次校准完成后可选择继续测量，重新选择通道和项目
- **自适应垂直位置**：小电压挡位自动调整示波器垂直位置，确保波形完整显示
- **配置驱动扩展**：新增示波器只需添加 JSON 文件，无需修改代码。支持 `manufacturer` / `models` 精确匹配
- **美观终端输出**：Rich 表格、进度条、超差红色高亮
- **Excel 报告导出**：数据表格 + 超差红色高亮，有效位数与终端表格一致
- **SCPI 通信重试**：瞬态错误自动重试（0.5s 间隔），避免偶发通信失败
- **单元测试**：pytest 测试套件覆盖指令集结构、Profile 校验、全量配置结构、模拟集成、CLI 流程（用例数随功能增长，以 CI 为准）
- **本地模拟运行**：内置模拟仪器脚本，无需真实设备即可跑通完整校准流程

## 环境要求

- Python >= 3.10
- VISA 运行时（如 [NI-VISA](https://www.ni.com/zh-cn/support/downloads/drivers/download.ni-visa.html)），用于 USB/GPIB/串口连接
- 网线连接无需 VISA 运行时

## 安装

推荐在**虚拟环境**中安装。本项目依赖 click / rich / PyVISA / pyvisa-py / openpyxl，这些库的版本要求可能与机器上其他项目冲突（例如其他项目锁定旧版 PyVISA），使用虚拟环境可完全隔离，避免版本冲突导致的 `ImportError`、依赖被降级等问题。

### 1. 获取代码

```bash
git clone <repository-url>
cd OscCal-CLI
```

### 2. 创建并激活虚拟环境

```bash
# 创建虚拟环境（用 .venv 作为目录名，已加入 .gitignore）
python -m venv .venv
```

> 机器上有多个 Python 时，请用满足版本要求的解释器创建（虚拟环境版本 = 创建时使用的解释器版本）：
> `py -3.11 -m venv .venv`（Windows）或 `python3.11 -m venv .venv`（Linux/macOS）。

按所用终端选择激活命令：

| 终端 | 激活命令 |
|------|---------|
| Windows PowerShell | `.\.venv\Scripts\Activate.ps1` |
| Windows CMD | `.venv\Scripts\activate.bat` |
| Windows Git Bash | `source .venv/Scripts/activate` |
| Linux / macOS | `source .venv/bin/activate` |

> PowerShell 若提示"禁止运行脚本/无法加载文件"，先执行 `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` 再激活（仅对当前终端窗口生效）。

激活成功后提示符前会出现 `(.venv)`，此时 `python` 与 `pip` 都指向该虚拟环境。

### 3. 在虚拟环境中安装

```bash
# 先升级虚拟环境内的 pip，避免旧版 pip 解析依赖失败
python -m pip install --upgrade pip

# 安装本项目（可编辑安装，源码改动立即生效）
pip install -e .

# 需要测试与代码检查工具（pytest / ruff / mypy）时一并安装
pip install -e ".[dev]"
```

### 4. 验证安装

```bash
# 1. 确认包装在当前虚拟环境（Location 应为 ...\.venv\Lib\site-packages）
pip show osccal

# 2. 确认 osccal 命令来自当前虚拟环境（应首先列出 .venv\Scripts\osccal.exe）
where.exe osccal        # Windows
which osccal            # Linux / macOS

# 3. 命令可用
osccal --version        # 应输出 osccal, version 0.1.0
```

> **不要只用 `osccal --version` 判断是否装好**：激活虚拟环境只是在 PATH **最前面插入** `.venv\Scripts`，并不会移除系统 Python 的 `Scripts` 目录。若虚拟环境里尚未安装本项目，系统里已有的那份 `osccal` 仍会被找到并执行（Windows 的 `osccal.exe` 内嵌了安装它时的解释器路径，所以实际运行的是系统 Python 与系统里的依赖）。判定依据用 `pip list`（是否列出 `osccal` 与依赖）、`pip show osccal`、`where/which osccal` 三者之一。
>
> 同理，在**项目根目录**执行 `python -c "import osccal"` 会因当前目录在 `sys.path` 中而"看似成功"，也不能作为安装验证；换到项目外目录执行才会报 `ModuleNotFoundError`。

安装完成后即可使用 `osccal` 命令。退出虚拟环境执行 `deactivate`。

### 未激活时直接调用（脚本 / CI）

脚本中也可以不激活，直接使用虚拟环境内的可执行文件：

```bash
.venv\Scripts\osccal.exe device list            # Windows
./.venv/bin/osccal device list                  # Linux / macOS

.venv\Scripts\python.exe simulate_calibrate.py  # Windows：用该环境跑本地模拟
./.venv/bin/python simulate_calibrate.py        # Linux / macOS
```

### Windows：输出重定向时的编码

`osccal` 命令与模拟脚本启动时会自动把标准输出/错误切换为 **UTF-8**。因此把输出重定向到文件或管道时（如 `osccal show > out.txt`、CI 日志收集），不会再因中文控制台的 GBK 编码无法表示 `✓`/`⚠`/`Δ`/表格边框而报 `UnicodeEncodeError`，输出文件即为 UTF-8 编码。

如需自行指定编码（例如管道对端程序要求 GBK），设置环境变量即可覆盖默认行为：

```powershell
$env:PYTHONIOENCODING = "gbk"    # PowerShell，仅对当前窗口生效
```

```bash
export PYTHONIOENCODING=gbk      # Linux / macOS / Git Bash
```

### 检查当前安装状态

以下命令作用于**当前已激活的环境**（虚拟环境或系统 Python）：

`osccal` 默认以可编辑安装（editable）方式安装，`osccal` 命令和 `import osccal` 都直接指向安装时的项目目录。检查当前指向：

```bash
# 查看 osccal 安装信息（Editable project location 即当前指向的源码目录）
pip show osccal

# 列出所有可编辑安装
pip list -e
```

若 `Editable project location` 指向了其他目录（例如从旧项目路径安装过），需要先卸载再重装。

### 卸载并重装（切换到当前项目）

```bash
# 1. 卸载旧安装（移除 .pth 指向与 osccal 命令脚本）
pip uninstall -y osccal

# 2. 进入当前项目目录，重新安装
cd <当前项目目录>
pip install -e .

# 3. 验证指向已切换
pip show osccal          # Editable project location 应指向当前目录
osccal --version         # 命令可用
python -c "import osccal; print(osccal.__file__)"   # 应输出当前目录下的 osccal/__init__.py
```

说明：

- 卸载只移除 Python 环境中的注册信息，**不会删除旧目录下的源码文件**；确认不再需要后可手动删除旧项目文件夹。
- 重装时会重新生成当前项目下的 `osccal.egg-info/`（已被 `.gitignore` 忽略）。
- 若旧安装位于**另一个环境**（系统 Python 或别的虚拟环境），`osccal` 命令可能来自那个环境。先激活旧环境执行 `pip uninstall -y osccal`，再激活当前虚拟环境执行 `pip install -e .`；用 `where osccal`（Windows）/ `which osccal`（Linux、macOS）可确认实际调用的是哪个环境的命令。
- 若曾在其他机器/环境遇到同样问题，执行上述 `pip uninstall` + `pip install -e .` 两步即可。

## 快速开始

### 1. 查看可用设备

```bash
osccal device list
```

### 2. 一键自动校准（推荐）

```bash
osccal calibrate --auto
```

程序将自动：
1. 扫描所有 VISA 资源
2. 查询每个资源的 `*IDN?` 识别设备身份
3. 自动匹配 FLUKE 校准仪和示波器（忽略无关设备）
4. 根据示波器型号精确匹配指令集和特征配置
5. 自动查询校准仪装载的探头型号
6. 打印识别结果供你确认
7. 确认后自动连接并开始校准

```bash
# 自动识别 + 指定探头
osccal calibrate --auto --probe 9530

# 自动识别 + 指定校准项目
osccal calibrate --auto --items amp,dc_gain
```

### 3. 交互模式校准

```bash
osccal calibrate
```

程序将引导你依次选择：
1. 校准仪探头型号
2. 示波器指令集文件
3. 示波器特征配置文件
4. 校准通道（支持多通道）
5. 校准项目
6. 带宽参数（如涉及带宽校准）
7. 校准仪 VISA 资源
8. 示波器 VISA 资源

多通道校准时，切换通道会暂停等待用户移动探头并确认接线。

校准完成后，可选择"继续校准"重新选择通道和项目再测一轮，或直接退出。数据自动保存到 `data/` 目录。

每轮校准使用包含微秒时间戳和 UUID 的独立 JSON 文件。开始执行及每个项目结束时更新同一文件：先写入同目录临时文件、刷新到磁盘，再原子替换，因此写入失败不会覆盖原有的完整记录。保存失败会停止后续校准。

Ctrl+C 或项目异常时，会保存已有结果（包括当前项目已经完成的数据点），并记录整体状态、各项目状态与失败原因；若进程被强制终止或断电，最近一次成功保存的项目阶段记录可供查看，当前项目尚未保存的数据点可能丢失。`show --latest` 和 Excel 的校准信息会显示状态，进行中、中断或失败的记录不代表完整校准已完成。

数据 `metadata.scpi_errors` 保存本轮错误次数；`metadata.failures` 保存失败项目与原因；`metadata.configurations` 保存实际使用的指令集、Profile 和校准仪配置副本及 SHA-256（包含本轮带宽参数和实际通信方式）。继续校准时创建新文件，错误计数按轮独立记录。旧格式文件仍可读取和导出。

执行前会核对通道范围、重复或未知项目、探头信号模式与阻抗、带宽参数、必需动作及设备身份。连接阶段允许进行身份和探头查询，只有检查通过后才复位设备并执行测量。Profile 的 `channels` 决定通道菜单和范围，旧配置未填写时兼容为 4 通道；两通道设备应明确填写 `channels: 2`。

设备身份核对规则：存在 `models` 列表时，设备型号必须包含在列表中（精确比较，忽略大小写与非字母数字字符）；校准仪配置未提供 `models` 时回退比较 `series`/`name`，按**型号家族**匹配——完全相同，或较短者为较长者的前缀且长度不少于 4 个字符。因此同一台 FLUKE 9500B 无论 `*IDN?` 上报 `9500B` 还是 `9500` 都能通过；报错信息会列出配置支持的全部型号，便于定位。

`calibrate` 退出码：`0` 表示所选项目执行完成；`1` 表示连接、存储或项目执行失败；`2` 表示参数、配置或设备组合不合法；`130` 表示用户取消或中断。连续多轮中任一轮有执行失败，最终退出码仍为 `1`。退出码 `0` 不表示所有测量值均在允差内，是否超差以结果中的误差和限值为准。

### 4. 查看校准结果

```bash
# 查看最近一次校准数据
osccal show --latest

# 查看指定文件
osccal show --file data/calibration_20260427_143000.json

# 交互选择文件
osccal show
```

### 5. 导出 Excel 报告

```bash
# 导出最近一次校准数据为 Excel
osccal export

# 指定输入和输出
osccal export --file data/calibration_20260427_143000.json --output report.xlsx
```

导出规则：

- 同一校准项目（如幅度）的**所有通道合并到同一个 sheet**，表头与终端表格一致。
- 单元格按**显示精度**整理，位数与校准过程中的终端表格相同：幅度、直流增益保留 3 位有效数字，Δt 保留 4 位，误差保留 2 位小数，带宽保留 2 位小数，探头上升时间取整。SCPI 直读值（如 `0.01232000000000001`、`7.96248e-08`）不会以原始位数出现在报告里。
- 整理后的仍是**数值单元格**（含数字格式，末尾零正常显示），可直接排序、统计、再计算；未舍入的原始读数完整保存在同目录的 JSON 记录中。
- **超差判定用未舍入的原始值**，因此显示为 `2.00%` 的单元格也可能被标红（实际 `2.004%`，上限 `2%`）。
- 各列的精度在 `osccal/core/table_configs.py` 的 `ITEM_PRECISION` 中集中声明，终端 `show` 与 Excel 导出共用。

## 本地模拟运行

无需真实示波器和校准仪，即可在本地跑通完整校准流程，便于开发调试和演示。模拟脚本内置两个实现 pyvisa 接口的模拟仪器，通过共享状态对象传递信号：校准仪 `write` 更新输出信号，示波器 `query` 据此返回合理的测量值，并按一阶低通模型模拟示波器 -3dB 带宽滚降。

> 请先激活虚拟环境（见[安装](#安装)第 2 步），确保使用本项目安装的依赖运行。

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
| `--auto` | 自动扫描 VISA 资源，识别设备并匹配配置 | — |
| `--osc` | 示波器指令集配置文件路径 | 交互选择 |
| `--profile` | 示波器特征配置文件路径 | 交互选择 |
| `--calibrator` | 校准仪配置文件路径 | 自动加载首个 |
| `--channel` | 校准通道，逗号分隔（1,2,3,4） | 交互选择 |
| `--probe` | 校准仪探头型号（9560/9550/9530） | 交互选择 / 自动识别 |
| `--items` | 校准项目，逗号分隔 | `all` |
| `--bandwidth` | 示波器标称带宽（MHz） | 交互输入 |
| `--bd-step` | 带宽扫描步进（MHz） | 交互输入 |
| `--resource-osc` | 示波器 VISA 资源地址 | 交互选择 |
| `--resource-cal` | 校准仪 VISA 资源地址 | 交互选择 |
| `--socket-osc` | 示波器 Socket 地址（host:port） | — |
| `--log-scpi` | 打印完整 SCPI 指令日志与失败统计（现场排障用） | 关闭 |

校准完成后若存在 SCPI 通信/组装失败，会在退出前提示失败次数，并将计数写入校准数据 `metadata.scpi_errors` 供报告追溯。

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
# 一键自动识别
osccal calibrate --auto

# 自动识别 + 指定探头和项目
osccal calibrate --auto --probe 9560 --items amp,dc_gain

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

数值按与 Excel 导出相同的显示精度打印（见[导出 Excel 报告](#5-导出-excel-报告)），超差判断仍用未舍入原值。

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
│   │   ├── auto_detect.py           # 自动识别设备与配置匹配
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
├── commands/                        # 示波器指令集配置
│   ├── tektronix_mdo.json           #   泰克 MDO3000/MDO4000/MSO4000B/DPO4000B
│   ├── tektronix_mdo3.json          #   泰克 3 Series MDO（MDO34/MDO32）
│   ├── tektronix_tbs.json           #   泰克 TBS2000B
│   ├── tektronix_tds.json           #   泰克 TDS5000
│   ├── tektronix_mso2000b.json      #   泰克 MSO2000B/DPO2000B/MSO2000/DPO2000
│   ├── rigol_mso.json               #   普源 MSO5000
│   ├── siglent_sds.json             #   鼎阳 SDS6000 PRO/SDS6000A
│   ├── unit_utd.json                #   优利德 UTD2000CEX/UTD7000C
│   ├── zlg_zds.json                 #   周立功 ZDS2000/ZDS4000
│   └── zlg_zds1000.json             #   周立功 ZDS1000
├── profiles/                        # 示波器特征配置
│   ├── tektronix_mdo3000.json       #   泰克 MDO3000 全系列
│   ├── tektronix_mdo34.json         #   泰克 MDO34（4 通道）
│   ├── tektronix_mdo32.json         #   泰克 MDO32（2 通道）
│   ├── tektronix_mso2000b_4ch.json  #   泰克 MSO2000B 系列（4 通道）
│   ├── tektronix_mso2000b_2ch.json  #   泰克 MSO2000B 系列（2 通道）
│   ├── tektronix_tbs2000b.json
│   ├── tektronix_tds5000.json
│   ├── rigol_mso5000.json
│   ├── siglent_sds.json
│   ├── unit_utd2000cex.json
│   ├── unit_utd7000c.json
│   ├── zlg_zds2000.json
│   ├── zlg_zds4000.json
│   └── zlg_zds1000.json
├── calibrators/                     # 校准仪配置
│   └── fluke_9500b.json             #   FLUKE 9500B（含探头 9560/9550/9530）
├── tests/                           # 单元测试（pytest，用例数随功能增长）
│   ├── conftest.py                  # 共享 fixture 与 FakeInstrument
│   ├── test_mdo3_commands.py        # MDO3 指令集结构测试
│   ├── test_mdo3_profiles.py        # MDO3 Profile 校验测试
│   ├── test_mdo3_comm_integration.py # SCPI 通信集成测试
│   └── test_all_configs.py          # 全量配置结构测试（commands/profiles/calibrators）
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
    "manufacturer": "Tektronix",
    "models": ["MDO3052", "MDO3054", "MDO3012", "..."],
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
| `manufacturer` | 厂商全称，用于自动识别匹配 |
| `models` | 适用型号列表，`--auto` 模式下精确匹配 `*IDN?` 型号 |
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
    "manufacturer": "Tektronix",
    "models": ["MDO3012", "MDO3014", "MDO3052", "MDO3054", "..."],
    "factor": "tektronix",
    "series": "MDO3000",
    "imp_has_50": true,
    "vertical_div": 8,
    "horizontal_div": 10,
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
| `manufacturer` | 厂商全称，用于自动识别匹配 |
| `models` | 适用型号列表，用于精确匹配 |
| `series` | 产品系列，用于模糊匹配（回退） |
| `imp_has_50` | 是否支持 50Ω 阻抗 |
| `channels` | 通道数；未填写时兼容为 4，两通道设备应明确填写 2 |
| `vertical_div` | 垂直方向分度数 |
| `horizontal_div` | 水平方向分度数 |
| `calibration_limits` | 各校准项目的允差限 |
| `points` | 各校准项目的校准点列表 |
| `bd_scan` | 带宽扫描模式：`bisect`（默认，指数粗定位+二分精化）或 `linear`（固定步进，旧方案） |

> **带宽扫描算法**：默认 `bisect` 模式利用频响单调性，用"指数粗定位（×2 探测）+ 栅格二分精化"定位 -3dB 点，测量次数从线性扫描的 O(范围/步长) 降为 O(log₂(范围/步长))（实测 1GHz 场景约 3.4× 提速）。每步的稳定/采集延时与线性模式完全一致，不改变校准仪与示波器间的时序；报告值仍落在 `bd_step` 栅格上。若某机型频响非单调（出现 peaking），可将 profile 的 `bd_scan` 改为 `linear` 回退旧方案。

### 校准仪文件（calibrators/）

定义校准仪的 SCPI 命令、探头信息和阻抗规则。

```json
{
    "name": "9500B",
    "description": "Fluke 9500B Oscilloscope Calibrator ...",
    "type": "pyvisa",
    "series": ["9500B"],
    "models": ["9500", "9500B"],
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
| `models` | 该配置接受的 `*IDN?` 型号字符串列表（精确比较）。用于同一型号存在多种上报形式的场景，如 FLUKE 9500B 既有上报 `9500B`、也有上报 `9500` 的固件，此时填写 `["9500","9500B"]`；省略时按 `series` 做型号家族回退匹配 |
| `probes` | 探头信息，`edge_rise_times` 为可用的上升时间列表（秒），`max_frequency` 为最大正弦波频率 |
| `impedance_rules` | 阻抗规则，按探头型号和信号模式定义支持的阻抗列表。`["1M","50"]` 表示两种都支持，`["50"]` 表示仅支持 50Ω |

## 自动识别流程

`osccal calibrate --auto` 的完整识别链条：

```
扫描 VISA 资源
  → *IDN? 查询（200ms 超时，超时=不可用，忽略）
    → 厂商含 "FLUKE" → 校准仪
    → 厂商为已知示波器厂商 → 示波器（多台同类设备时要求指定资源）
    → 其他 → 忽略
  → 指令集匹配：models 精确匹配 → series 模糊匹配 → 文件名前缀回退
  → 特征匹配：同上三级回退
  → 连接校准仪 → ROUT:FITT? CH1 查询探头 → 自动匹配探头型号
  → 打印识别结果 → 用户确认 → 执行
```

自动模式与手动模式共用配置校验。空厂商或型号、重复精确匹配和系列匹配同分时均不会自动选取；可切换到手动模式显式选择配置。检测到多台同类设备时，用 `--resource-cal` 和 `--resource-osc` 指定资源。配置会检查必需动作、测量模式所需动作、参数数量和字段类型，以及校准点和限值的有限数值约束。

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

在 `commands/` 目录下新建 JSON 文件，定义示波器的 SCPI 命令模板。需要填写：
- `manufacturer`：厂商全称（如 `"Tektronix"`）
- `models`：适用型号列表（如 `["MDO3052", "MDO3054"]`），用于 `--auto` 精确匹配
- `series`：产品系列（如 `["MDO3000"]`），用于模糊匹配回退
- SCPI 命令模板

可参考已有文件（如 `commands/tektronix_mdo.json`）的格式。

### 2. 创建特征文件

在 `profiles/` 目录下新建 JSON 文件，定义示波器的硬件参数和校准点。同样需要填写 `manufacturer` 和 `models` 字段。可参考已有文件（如 `profiles/tektronix_mdo3000.json`）的格式。

完成后运行 `osccal calibrate --auto`，程序会自动根据 `*IDN?` 型号匹配新配置。

## 校准项目说明

### 幅度（ΔV）

校准垂直偏转系数幅度准确度。校准仪输出方波信号（SQU），示波器测量幅度值，计算相对误差：

```
误差(%) = (测量值 - 标准值) / 标准值 × 100%
```

幅度、直流增益和 Δt 均用原始数值计算误差，JSON 保留未舍入的误差。终端和 Excel 只显示有效位数（幅度/直流增益 3 位有效数字、Δt 4 位、误差小数点后 2 位），超差判断仍使用未舍入值，因此显示为 `2.00%` 的值也可能被标红（如实际为 `2.004%`，上限为 `2%`）。

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

扫描起点必须在 50 kHz 至探头最高频率之间，步进至少为 1 Hz；参数不合法时不会开启输出。搜索到最低栅格仍无通过点时，报告项目失败并退出搜索。若最高可测栅格仍通过，则 JSON、终端和 Excel 的“结果状态”标记为“下界（未定位交叉点）”，数值仅表示已验证的带宽下界，不能作为精确带宽或据此判定低于标称值。

通信重试耗尽、无效读数（包括 NaN、无穷大和仪器无效值标记）会终止当前项目，不再以零值参与计算。直流增益使用未舍入的读数计算，零增益作为无效结果处理。各校准项目正常结束、异常或 Ctrl+C 中断时均尝试关闭校准仪输出；关闭失败会终止会话并提示检查设备输出状态。

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
| 泰克 | MSO2000B, DPO2000B, MSO2000, DPO2000（4 通道） | `tektronix_mso2000b.json` | `tektronix_mso2000b_4ch.json` | VISA |
| 泰克 | MSO2000B, DPO2000B, MSO2000, DPO2000（2 通道） | `tektronix_mso2000b.json` | `tektronix_mso2000b_2ch.json` | VISA |
| 普源 | MSO5000 | `rigol_mso.json` | `rigol_mso5000.json` | VISA |
| 鼎阳 | SDS6000 PRO, SDS6000A | `siglent_sds.json` | `siglent_sds.json` | VISA |
| 优利德 | UTD2000CEX | `unit_utd.json` | `unit_utd2000cex.json` | VISA |
| 优利德 | UTD7000C | `unit_utd.json` | `unit_utd7000c.json` | VISA |
| 周立功 | ZDS2000/2000B | `zlg_zds.json` | `zlg_zds2000.json` | Socket |
| 周立功 | ZDS4000/3000 | `zlg_zds.json` | `zlg_zds4000.json` | Socket |
| 周立功 | ZDS1000 | `zlg_zds1000.json` | `zlg_zds1000.json` | Socket |

## 泰克 MSO2000B/DPO2000 系列特别说明

该系列（MSO2000B/DPO2000B/MSO2000/DPO2000，2 通道与 4 通道共 18 个型号，覆盖 70/100/200 MHz）**输入阻抗仅 1 MΩ**，配置与使用方法如下：

- **探头选择**：9560 探头的 MARK/SIN/EDGE 模式只能输出 50Ω，与本系列不匹配，执行前校验会拒绝 `delta_time`、`bandwidth`、`transient`。上述项目请改用 **9530 探头**（各模式均支持 1MΩ）；`amp` 与 `dc_gain` 用 9530 或 9560 均可。
- **探头增益**：出厂 P2220 探头默认 10×，Profile 中 `probe_default: 10` 会在测量前把探头增益置为 1×（对应校准仪直连），避免读数差 10 倍。
- **无 50Ω 选项**：手册中 `CH<x>:TERmination` 与 `CH<x>:IMPedance` 均为"为兼容性保留"的**无参数命令**，无法通过 SCPI 选择 50Ω，故指令集不含 `set_impedance`。
- **垂直挡位范围 2 mV/div ～ 5 V/div**（手册偏移量说明："For V/Div settings from 2 mV/div to 200 mV/div, the offset range is ±1 V；from 202 mV/div to 5 V/div, the offset range is ±25 V"），按 1-2-5 排列，**不支持 1 mV/div 与 10 V/div**；**水平时基按 1-2-4-10 排列**（400 ns/div 之后直接是 1 µs/div，**没有 800 ns/div**）。因此本系列的 `delta_amp`/`dc_gain` 点表为 11 点（2 mV ～ 5 V/div）、`delta_time` 点表以 1 µs 取代 800 ns（20 点），避免示波器钳位挡位后标准值与被测波形不符而报出虚假大误差。
- **时基下限 2 ns/div**：频带宽度扫描在约 250 MHz 以上会触及该下限，示波器自行钳位时基；幅度—频率测量本身仍然有效。
- 其他已核实要点：`ACQuire:MODe` 仅支持 `SAMple|AVErage`（无峰值检测）；触发电平为全局 `TRIGger:A:LEVel <NR3>`（不带通道号）；测量值查询返回 `:MEASUREMENT:IMMED:VALUE <值>`（配置 `return_value_index: 1`）。

## 周立功 ZDS1000 系列特别说明

ZDS1000 系列使用 **完整 SCPI 关键字**（`:CHANnel`/`:MEASure`/`:TIMebase`/`:ACQuire`/`:TRIGger`），与 ZDS2000/4000 系列不兼容。主要差异：

- **无 50Ω 输入阻抗**，EDGE 校准自动切换为 1MΩ + 500ps 上升时间
- **直流均值测量**使用 `VAVG DISPlay` 替代 `VMEAn`（VMEAn 不支持 DC 信号）
- **垂直偏置**使用 `:CHANnel<n>:OFFSet`（伏特单位），代码已自动适配
- **瞬态测量**需提前设好测量项再 SINGLE 捕获，否则返回 Invalid
- 小挡位（≤5mV/div）跳过自动垂直位置调整（`skip_vertical_adjust: true`）

## 测试

项目使用 pytest 进行单元测试，覆盖指令集结构、Profile 校验和 SCPI 通信集成。

> 需先激活虚拟环境并安装开发依赖：`pip install -e ".[dev]"`（见[安装](#安装)）。

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
| `tests/test_all_configs.py` | 全量配置结构校验：commands/ 指令集 action/keyword 契约、profiles/ 校准点与限值、calibrators/ 探头阻抗规则 |
| `tests/test_sim_integration.py` | 模拟仪器端到端集成测试：无硬件跑通全部校准项目，含带宽向下扫描边界用例 |
| `tests/test_cli_flow.py` | CLI 校准流程测试：手动/自动模式、`--log-scpi`、SCPI 失败统计（mock 设备） |
| `tests/test_device_identity.py` | 设备身份核对：厂商别名/跨厂商拒绝、`models` 白名单精确匹配、校准仪 `series` 型号家族回退（`9500`/`9500B` 兼容） |
| `tests/test_export_grouping.py` | 报告分组：同一项目的多通道数据合并到同一 sheet / 同一表格 |
| `tests/test_export_precision.py` | 报告显示精度：`ITEM_PRECISION` 与列数一致性、Excel 单元格数值/数字格式与终端位数一致、舍入不掩盖超差 |

> 配置结构校验规则与运行时加载校验共用同一实现（`osccal/core/config_validation.py`）：
> 加载配置时即校验结构，出错会直接指出具体 JSON 文件与字段，而非运行时才报错。

## 依赖

| 库 | 用途 |
|---|---|
| [click](https://click.palletsprojects.com/) | CLI 命令框架 |
| [rich](https://rich.readthedocs.io/) | 终端美观输出 |
| [PyVISA](https://pyvisa.readthedocs.io/) | VISA 仪器通信 |
| [PyVISA-py](https://pyvisa-py.readthedocs.io/) | PyVISA 纯 Python 后端 |
| [openpyxl](https://openpyxl.readthedocs.io/) | Excel 报告生成 |

开发依赖（`pip install -e ".[dev]"`）：

| 库 | 用途 |
|---|---|
| [pytest](https://docs.pytest.org/) | 单元测试与集成测试框架 |
| [ruff](https://docs.astral.sh/ruff/) | 代码 lint 与格式化 |
| [mypy](https://mypy.readthedocs.io/) | 静态类型检查（配置类型模块） |
| [pre-commit](https://pre-commit.com/) | Git 提交前钩子（可选） |

代码质量检查（CI 与本地一致）：

```bash
ruff check .                 # lint
ruff format --check osccal tests simulate_calibrate.py   # 格式检查
mypy                         # 类型检查
pytest                       # 全量测试
```

项目自带 GitHub Actions CI（`.github/workflows/ci.yml`），在 Python 3.10–3.13 上执行上述全部检查。

## License

MIT
