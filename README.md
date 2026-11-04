# OscCal-CLI

数字示波器自动校准命令行工具。通过 SCPI 同时控制 **FLUKE 9500B 校准仪**与被校示波器，
按 **JJF 1057-2026《数字示波器校准规范》** 第 7 章逐项取点、测量并记录结果，
输出可追溯的 JSON 原始记录与 Excel 报告。

| 项 | 当前状态 |
|---|---|
| 版本 | **v0.2.0**（相对 V0.1.0 完全重写，无兼容层） |
| 依据规范 | JJF 1057-2026，2027-02-21 实施，复校间隔 12 个月 |
| 实机验证过的硬件 | Tektronix MDO3052 + Fluke 9500B（9530 头） |
| 实机验证 | 2026-10-23，10/10 项有实测数据；结论见 [`verification/jjf1057_2026.json`](verification/jjf1057_2026.json) |
| 结论口径 | 规范表 1 明确"技术指标仅供参考，不作为符合性判定依据"，程序**不出具合格/不合格结论** |

## 目录

1. [支持范围](#1-支持范围)
2. [安装](#2-安装)
3. [快速开始](#3-快速开始)
4. [命令参考](#4-命令参考)
5. [校准项目与实现口径](#5-校准项目与实现口径)
6. [硬件验证状态](#6-硬件验证状态)
7. [记录、报告与追溯](#7-记录报告与追溯)
8. [架构与配置契约](#8-架构与配置契约)
9. [开发与测试](#9-开发与测试)
10. [已知限制](#10-已知限制)
11. [版本与兼容性](#11-版本与兼容性)

## 1. 支持范围

### 1.1 硬件

| 角色 | 型号 | 说明 |
|---|---|---|
| 被校示波器 | Tektronix **MDO3052**（500 MHz，2 通道） | 已实机验证 |
| 被校示波器 | Tektronix **MDO3032**（350 MHz，2 通道） | 同系列 350 MHz 机型，仅补了 profile，**验证台账未覆盖** |
| 标准器 | Fluke **9500B**（GPIB/USB） | 已实机验证 |
| 有源探头 | **9530**（600 MHz，边沿 150 ps / 500 ps） | 已实机验证，10 项全部使用 |
| 有源探头 | 9550（25 ps）、9560（6.4 GHz，70 ps） | 配置已声明，**未实机验证** |

> `profiles/` 目前只有 MDO3052 / MDO3032 两份。`commands/` 下保留的其他品牌指令集
> （Rigol、Siglent、UNI-T、ZLG、Tektronix 老系列）属于 V0.1.0 遗留，**没有对应的
> v0.2.0 profile，`--auto` 无法匹配、也不能执行**；补齐 profile 并完成实机验证后才算支持。

### 1.2 校准项目

JJF 1057-2026 第 7 章的 10 个项目全部实现，项目键与条款如下（命令 `--items` 使用的就是这些键）：

| 项目键 | 条款 | 项目 | 取点策略 | MDO3052 单通道点数 |
|---|---|---|---|---|
| `input_impedance` | 7.3.1 | 输入阻抗 | 每通道 × 每阻抗状态 | 2 |
| `dc_gain` | 7.4.1 / 7.4.2 / 7.4.3 | 直流增益（三法并列） | 垂直档位列表 | 6 |
| `dc_offset` | 7.5.1 / 7.5.2 | 直流偏置（两法并列） | 垂直档位列表 | 4 |
| `freq_response_bandwidth` | 7.6 | 频率响应、频带宽度 | 相对标称带宽的比值频点 | 9 |
| `enob` | 7.7 | 动态有效位数 | 现场按公式反推 | 1 |
| `rise_time` | 7.8 | 上升时间 | 每通道 × 每边沿速度档 | 2 |
| `timebase_error` | 7.9.1 / 7.9.2 | 时基（采集速率）误差 | 水平档位列表 | 4 |
| `delta_v` | 7.11 | ΔV（幅度）测量 | 垂直档位列表 | 4 |
| `delta_t` | 7.12 | Δt（时间）测量 | 水平档位列表 | 2 |
| `random_noise` | 7.13 | 随机噪声 | 固定条件（最小量程） | 1 |

合计 **35 点/通道**（MDO3052 + 9500B/9530），另有 6 处按规范不可执行或超出标准器能力而跳过
（2 项规范定为人工、2 个 50 Ω 档位超 5 Vpp 上限、2 个快时基超出方波 10 kHz 上限），
逐条原因见 `osccal plan` 输出与记录中的 `skipped_points`。

### 1.3 程序不做的事

- 不做合格判定，不输出"超差/合格"字样；只给出实测值与参考指标。
- 不评定测量不确定度（按规范偏离声明，由实验室依 JJF 1059.1 另行评定）。
- 不自动接匹配负载（随机噪声项暂停并提示人工确认）。
- 不实现 7.2 外观检查、7.10 自校准信号（规范要求人工/需要频率计与数字电压表）。

## 2. 安装

### 2.1 环境要求

- Python ≥ 3.10（CI 覆盖 3.10–3.13）
- 与仪器通信的 VISA 运行时（如 NI-VISA）用于 USB / GPIB；网线 Socket 连接不需要 VISA
- 依赖：click、rich、PyVISA、PyVISA-py、openpyxl

### 2.2 创建虚拟环境并安装

```bash
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# Linux / macOS
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -e ".[dev]"     # 含 pytest / ruff / mypy
```

PowerShell 提示"禁止运行脚本"时，先执行
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`（仅当前窗口生效）。

### 2.3 验证安装

```bash
pip show osccal                 # Editable project location 应指向本仓库
where.exe osccal                # Windows；Linux/macOS 用 which
osccal --version                # osccal, version 0.2.0
```

> 仅看 `osccal --version` 不足以证明装对：激活虚拟环境只是把 `.venv\Scripts` 插到 PATH 最前，
> 系统里若已装过 `osccal` 仍可能被执行。以 `pip show osccal` 的 Editable 路径为准。

### 2.4 输出编码

程序启动时把 stdout/stderr 切到 UTF-8，重定向到文件或管道不会再因 GBK 无法表示
`✓`/`Δ`/表格边框而报 `UnicodeEncodeError`。如需覆盖，设置环境变量 `PYTHONIOENCODING`（如 `gbk`）。

## 3. 快速开始

```bash
# 1) 看设备
osccal device list

# 2) 离线核对校准点表（不连仪器，先确认点数与跳过原因）
osccal plan --profile profiles/tektronix_mdo3052.json --probe 9530 --channel 1

# 3) 自动识别设备并校准（--spec 默认 jjf1057_2026，可省略）
osccal calibrate --auto --spec jjf1057_2026 --probe 9530

# 4) 查看 / 导出
osccal show --latest
osccal export
```

`calibrate --auto` 的连接与执行顺序：

```
扫描/指定 VISA 资源 → *IDN? 识别 → 匹配 commands + profile + calibrator
→ 查询已装探头（ROUT:FITT?）→ 打印识别结果并确认
→ 设备身份核对 → 按 specs 解析点表 → 逐项执行 → 每项结束原子保存记录
```

多通道时，切换到下一个通道前会暂停，等待把探头接到对应通道后按回车。

## 4. 命令参考

### 4.1 `osccal calibrate`

```bash
osccal calibrate [OPTIONS]
```

| 选项 | 说明 |
|---|---|
| `--auto` | 扫描 VISA 资源，按 `*IDN?` 自动识别设备并匹配配置 |
| `--osc PATH` | 示波器指令集文件（默认交互选择） |
| `--profile PATH` | 示波器 profile（默认交互选择） |
| `--spec NAME 或 PATH` | 校准规范：`specs/` 下名称（可省 `.json`）或文件路径，默认 `jjf1057_2026` |
| `--calibrator PATH` | 校准仪配置（默认取目录中首个） |
| `--channel 1,2` | 通道，逗号分隔（MDO3052 共 2 通道） |
| `--probe 9530 / 9550 / 9560` | 有源探头型号；`--auto` 下省略则自动识别 |
| `--items a,b` | 校准项目键，逗号分隔；`all` 表示规范中所有已实现的项目 |
| `--resource-osc` / `--resource-cal` | 指定 VISA 资源地址 |
| `--socket-osc host:port` | 示波器走 Socket 连接（仅标量测量项可用，见[已知限制](#10-已知限制)） |
| `--log-scpi` | 退出前打印完整 SCPI 指令日志与失败统计 |

示例：

```bash
# 自动识别 + 指定探头，跑全部 10 项
osccal calibrate --auto --spec jjf1057_2026 --probe 9530

# 只跑直流类两项，通道 1
osccal calibrate --auto --spec jjf1057_2026 --probe 9530 --channel 1 --items dc_gain,dc_offset

# 手动指定全部配置与资源
osccal calibrate \
  --osc commands/tektronix_mdo.json \
  --profile profiles/tektronix_mdo3052.json \
  --spec jjf1057_2026 \
  --calibrator calibrators/fluke_9500b.json \
  --probe 9530 --channel 1 \
  --resource-cal "GPIB0::19::INSTR" \
  --resource-osc "USB0::0x0699::0x0408::C020687::INSTR"
```

退出码：

| 退出码 | 含义 |
|---|---|
| `0` | 所选项目执行完毕（不代表测量值在参考指标内） |
| `1` | 连接、存储或项目执行失败 |
| `2` | 参数、配置或设备身份核对不通过（未下发任何设置指令） |
| `130` | 用户取消或 Ctrl+C 中断 |

单项失败不会终止后续项目：失败项目记为 `failed`（已测到的数据点保留在 JSON 中便于诊断，
但 `show`/Excel 不展示），后续项目继续执行，本轮状态为 `completed_with_errors`、退出码 `1`。
用户中断（Ctrl+C）或"无法关闭校准仪输出"时仍立即终止本轮；已完成项目的记录会保存。

### 4.2 `osccal plan`

只做点表解析，**不连接任何仪器**，用于执行前核对。

```bash
osccal plan --profile profiles/tektronix_mdo3052.json --probe 9530 --channel 1,2
osccal plan --json data/plan.json
```

输出每个项目的条款、取点策略、点数、跳过数，并逐条打印跳过原因。
解析输入为 `specs/`（规范口径）+ `profiles/`（硬件事实）+ `calibrators/`（标准器能力）。

### 4.3 `osccal show`

```bash
osccal show --latest                       # 最近一次
osccal show --file data/calibration_xxx.json
osccal show                                # 交互选择
```

按项目输出表格（表名沿用规范附录 A 的记录表号），表尾打印参考指标与
"仅供参考、不作符合性判定依据"的说明。

### 4.4 `osccal export`

```bash
osccal export                              # 最近一次 → 同目录同名 .xlsx
osccal export --file data/xxx.json --output report.xlsx
```

- 每个校准项目一张工作表，表名用规范附录 A 的编号与名称（如 `A.3 直流增益`）；
- 同一项目的多个通道合并到同一张表；
- 单元格按与 `show` 相同的显示精度舍入，仍是数值单元格；
- 表尾给出参考指标文本与免责说明，**不做合格/超差判定**；
- 首张"校准信息"表记录时间、状态、设备身份、依据规范（含 sha256）与逐条偏离声明。

### 4.5 `osccal device`

```bash
osccal device list                 # 列出 VISA 资源
osccal device info --resource "GPIB0::19::INSTR"
osccal device info --socket 192.168.1.100:5025
```

## 5. 校准项目与实现口径

所有项目均为：按 `specs/` 的取点策略生成点 → 设激励与示波器状态 → 读数 → 写记录。
公共约定：

- **每次读数前重新采集**，并用 `ACQuire:STATE?` 轮询确认采集结束，避免读到上一次的陈旧值；
- **直流/无沿信号自由运行**，不走"单次采集等触发"（等不到触发会白等 5 s）；
- **读数收敛判据**：标准源换函数后幅度约 2 s 才建立，幅度/频率/周期等标量读数按
  "间隔 0.5 s 连读、相对差 ≤0.1%"判定收敛，等待时间与残差写入记录（直流扫描点仍用固定建立时间）；
- **记录长度 = 分析点数**（ENOB、拟合、偏置），否则示波器返回的数据与 `XINCR` 不匹配；
- **阻抗两端一起设并回读校验**：示波器与校准仪的输入/输出阻抗必须同时匹配（50 Ω 输出接 1 MΩ 输入会让读数翻倍），
  设置后回读两端阻抗，不一致立即告警。

各项目实现要点：

| 项目 | 激励 | 读数与算法 |
|---|---|---|
| 输入阻抗 | 9500B 有源头 `CONF:RES` / `CONF:CAP` | 读校准仪的电阻/电容，与标称值比较；`2E35` 判为无效 |
| 直流增益 | DC / 1 kHz 对称方波 | 方法一（7.4.1）屏 90%/10% 两点；方法二（7.4.2）方波幅度 `G=Vr/V`；方法三（7.4.3）16 点最小二乘，同时给截距 |
| 直流偏置 | DC，偏置 0 与 2 格 | 方法二按 7.5.2：读原始码值 `(码值−YOFf)×YMUlt`（不叠加 YZEro）后扫 16 点拟合，`d_c=−b`；方法一按 7.5.1 两点（激励取与 d₀ 同号） |
| 频率响应 | 正弦 0.5 Vpp | 以 50 kHz 为基准，`G=Vk/V0`；在相邻频点间按对数频率插值求 0.707 |
| ENOB | 正弦，峰值约 95% 量程 | 采样率现场读回，`f=fs·n/N`（N=1000、n=7 互质），附录 E 四参数拟合，`ENOB=log2(V0/(√12·Er))` |
| 上升时间 | 快沿，匹配阻抗（50 Ω） | `RIS` 测量项读 10%~90% 过渡时间，10 次独立采集平均，同时记录正过冲与标准差 |
| 时基误差 | 正弦 | 方法一（7.9.1）频率读数 `δT=(f_std−f_read)/f_std`；方法二（7.9.2）波形拟合 `δT=f_std/f_app−1`，并校验拟合频率与读数一致（>5% 判时间轴不可信） |
| ΔV | 1 kHz 对称方波 | 自动幅度测量读数代替光标，误差相对标准值 |
| Δt | 1 kHz 对称方波 | 周期测量 ×M（M=2）与标准值比较 |
| 随机噪声 | 输入端接 50 Ω 匹配负载（人工确认） | 最小量程、最高采样率下取 1000 点波形求标准差，占满量程百分比 |

**已知与规范的偏离**（写入记录 `metadata.spec.deviations`）：

1. ΔV、Δt 用示波器自动测量读数代替 7.11/7.12 要求的"移动测量光标读数"；
2. 本记录不包含测量不确定度，由实验室按 JJF 1059.1 另行评定；
3. 7.13 随机噪声为人工确认环节，程序暂停并提示接入匹配负载。

**实现约定（规范未逐字规定、以实机可行性为准）**：

- 直流偏置方法一的激励取与 d₀ **同号**（规范原文为 −d₀，取负号会把波形推出约两倍偏置量、无法读数）；
- 零点测量用 **±1 mV 两点插值**：9500B 的 `SOUR:VOLT 0` 会被静默丢弃（最小可设约 1 mV）；
- 上升时间按图 9 接**匹配阻抗**：机型有 50 Ω 输入时用 50 Ω 端接，没有时退为 1 MΩ 并在记录中注明；
- 直流偏置误差按 `δd = d_r − d₀` 记录（与 `offset_error_v` 字段同号）。
- 直流增益三种方法在同一次运行里对同一点各测一遍，并列保存以便互相印证。

> 参考指标来自规范表 1，只作参照；终端与 Excel 均不给出合格/不合格结论。

## 6. 硬件验证状态

验证条件：MDO3052（SN C020687，FW CF:91.1CT FV:v1.30）+ 9500B（SN 045029，FW 4.11，9530 头 SN 882750012，
证书 WWM202600225，检定日期 2026-03-03；快沿 146 ps、主输出上升时间 409 ps）。
逐项实测数据、偏离、限制与记录文件见 [`verification/jjf1057_2026.json`](verification/jjf1057_2026.json)。

| 项目 | 状态 | 关键结果 |
|---|---|---|
| 输入阻抗 | verified | 1 MΩ：−0.290%；50 Ω：+0.050% |
| 直流增益 | verified | 三方法误差 0.000% ~ +0.625%，方法间互差 <0.42% |
| 直流偏置 | deviation | 方法一 Δd +0.7 ~ +19.2 mV；方法二 −0.9 ~ −47.4 mV；零点 −19.6 ~ +1.4 mV |
| 频率响应 | verified_with_caveat | 500 MHz 处 G=0.726，测试范围内未出现 −3 dB 点 → 带宽 ≥500 MHz |
| 动态有效位数 | verified_with_caveat | 2.5 GS/s、17.5 MHz、1.52 Vpp 下 6.20 bit |
| 上升时间 | verified_with_caveat | 150 ps 边沿读 807.0 ps，500 ps 边沿读 865.4 ps，差 58.4±20.9 ps |
| 时基误差 | verified_with_caveat | 频率法 −1767 ~ +1250 ppm（受读数位数限制），拟合法 −366 ~ +127 ppm |
| ΔV | deviation | 误差 0.000% ~ +0.625%（自动测量代替光标） |
| Δt | deviation | 误差 0.000%（自动测量代替光标） |
| 随机噪声 | verified_with_caveat | 0.179 mV = 2.243% FS（1 mV/div 本底） |

`verified_with_caveat` 表示测量完成但存在需注明的限制（分辨率、重复性、外部条件）；
`deviation` 表示与规范方法存在偏离，已在 `deviations` 中声明。状态描述的是
**测量是否完成且可信**，不是合格判定。

## 7. 记录、报告与追溯

### 7.1 文件位置

`data/calibration_<YYYYmmdd_HHMMSS_微秒>_<uuid>.json`（`data/` 已被 gitignore）。
同一轮校准从开始到结束只写同一个文件：先写同目录临时文件、`fsync`、再 `os.replace` 原子替换，
写入失败不会破坏上一份完整记录。

### 7.2 记录结构

```jsonc
{
  "metadata": {
    "timestamp": "...", "status": "completed|completed_with_errors|interrupted|failed",
    "channel": "1", "probe": "9530",
    "oscilloscope": {"manufacturer": "...", "model": "...", "serial": "...", "firmware": "..."},
    "calibrator":   {"manufacturer": "...", "model": "...", "serial": "...", "firmware": "..."},
    "commands_file": "...", "profile_file": "...", "calibrator_file": "...",
    "spec": {"spec_code": "JJF 1057-2026", "file": "...", "sha256": "...",
             "deviations": [...], "limits_semantics": {...}},
    "points_plan": {"1": {"dc_gain": 6, "...": 0}},
    "skipped_points": [{"item": "Δt（时间）测量", "reason": "..."}],
    "requested_items": [...], "item_status": {"dc_gain": "failed", "delta_v": "completed"},
    "failures": {"dc_gain": {"type": "ScpiError", "message": "..."}},
    "error": {"type": "...", "message": "..."},
    "scpi_errors": 0,
    "configurations": {"commands": {"sha256": "...", "data": {...}}, "profile": {...}, "calibrator": {...}}
  },
  "results": {
    "dc_gain": [ {"index": 1, "channel": "1", "gain": 1.0012, "...": "..."} ]
  }
}
```

- 多通道时结果键为 `<item>_ch<通道>`；
- 原始读数（未舍入）只保存在这里，终端与 Excel 显示的是按精度舍入后的值；
- `metadata.item_status` 逐项记录 `completed` / `failed`；失败项目的已测点保留在 `results` 中，
  但 `show` 与 Excel 会跳过该项，失败原因在 `metadata.failures`；
- `metadata.configurations` 保存本次实际使用的指令集 / profile / 校准仪配置副本与 sha256，
  配置文件事后被修改也能追溯。

### 7.3 精度与显示

列定义与显示精度只有一份声明：`osccal/core/table_configs.py` 的 `ITEM_CONFIGS`
与 `ITEM_PRECISION`。终端 `show` 与 Excel 导出共用 `core/utils.py` 的格式化函数，
新增/删除列时两处自动一致（`tests/test_report.py` 守护列数与精度数量一致）。

## 8. 架构与配置契约

### 8.1 目录

```
osccal/
├── cli.py                    # 命令入口（calibrate / plan / show / export / device）
├── core/
│   ├── points.py             # 点表解析器：specs + profiles + calibrators → 点表
│   ├── config.py             # JSON 加载（加载即校验）
│   ├── config_validation.py  # 唯一的配置结构校验实现
│   ├── comm.py               # SCPI 读写/重试/二进制块读取/无效值处理
│   ├── connect.py            # VISA / Socket 连接与设备释放
│   ├── command.py            # 命令模板组装
│   ├── waveform.py           # WFMOutpre? 与 IEEE 488.2 块解析（纯函数）
│   ├── fitting.py            # 正弦四参数最小二乘（附录 E）
│   ├── storage.py            # 记录原子保存 / 配置快照 / 状态
│   ├── export.py             # Excel 报告
│   ├── table_configs.py      # 终端与 Excel 的列/精度/参考指标
│   ├── auto_detect.py        # --auto 设备与配置匹配
│   ├── scpi_trace.py         # SCPI 日志与失败计数
│   ├── types.py              # TypedDict 配置类型
│   └── utils.py              # 编码、格式化、误差
└── measure/
    ├── base.py               # 基类：连接、采集、读数收敛、波形读回、阻抗、表格
    ├── registry.py           # 项目清单 + 执行顺序 + RUNNERS
    ├── all.py                # 按序执行项目，未实现项直接报错
    └── <10 个项目>.py         # 每项一个 runner
specs/          # 规范口径（条款、取点策略、屏占比、偏离、参考指标）
profiles/       # 硬件事实（型号、通道数、格线、档位集合、标称带宽、最高采样率）
calibrators/    # 标准器能力（探头、阻抗规则、输出上下限）
commands/       # 示波器 SCPI 指令模板与能力声明
verification/   # 实机验证台账
tests/          # pytest
data/           # 运行产物（gitignore）
```

### 8.2 三层配置

| 目录 | 只写什么 | 不写什么 |
|---|---|---|
| `specs/` | 规范要求：条款号、取点策略与参数、屏占比、偏离声明、`reference_limits`、判据语义 | 硬件能力、具体型号 |
| `profiles/` | 硬件事实：`models`、`channels`、`imp_has_50`、`bandwidth_hz`、`vertical_scales`、`horizontal_scales`、`max_sample_rate_hz`、格线数 | 校准点、限值 |
| `calibrators/` | 标准器：`probes`（边沿、最高频率）、`impedance_rules`、`output_limits`、SCPI actions | 被校设备信息 |

三者由 `core/points.py` 合成点表，共 8 种策略：`channel_x_impedance`、`scale_list`、
`bw_ratio`、`derived`、`fixed`、`channel_x_edge_speed`、`explicit`、`screen_fraction`。
点表层面不做静默降级：任何超出标准器能力或机型不支持的点都会进入 `skipped` 并写明原因。
（指令集缺少某项可选能力时，个别项目会跳过对应设置，当前版本尚未恢复执行前的能力完整性检查。）

### 8.3 新增一款示波器

1. 在 `commands/` 新建指令集：`manufacturer`/`models`/`series`、`feature`（测量模式）、
   `keyword`（测量助记符）、`actions`（SCPI 模板）。校验规则见 `config_validation.validate_commands`。
2. 在 `profiles/` 新建 profile：只写硬件事实，不含点表与限值。
3. 用 `osccal plan --profile ...` 核对点表与跳过原因。
4. 实机跑通全部项目，测得的点数、最大偏差、固件版本写入 `verification/*.json`。
5. 更新本文档的"支持范围"与"硬件验证状态"两节。

> 版本号只有一处来源：`osccal/__init__.py:__version__`；`pyproject.toml` 用
> `dynamic = ["version"]` 引用它，不要在别处写死（`tests/test_specs.py` 守护）。

## 9. 开发与测试

### 9.1 质量门禁（与 CI 一致）

```bash
.venv\Scripts\ruff check .                                  # Windows
.venv\Scripts\ruff format --check osccal tests simulate_calibrate.py
.venv\Scripts\mypy
.venv\Scripts\pytest
```

Linux/macOS 把 `.venv\Scripts\` 换成 `.venv/bin/`。
`mypy` 只检查 `pyproject.toml` 里列出的 4 个模块；`ruff format` 不覆盖
`commands/ profiles/ calibrators/`（JSON 目录）。

### 9.2 测试范围（约 456 个用例，以 CI 为准）

| 文件 | 覆盖 |
|---|---|
| `test_specs.py` | 规范配置契约（条款、策略、参考指标语义、偏离声明）、版本号唯一来源 |
| `test_plan.py` | 点表解析：各取点策略、跳过原因、频点与点数 |
| `test_runners*.py` | 10 个项目 runner 的读数、算法、记录字段（假仪器） |
| `test_impedance.py` | 阻抗设置/回读校验、通道号传递、回读值解析 |
| `test_waveform.py` | 前导信息解析、块头/字节序/有符号解码、电压与时间轴 |
| `test_fitting.py` | 正弦拟合精度、异常输入、ENOB 公式 |
| `test_mdo3_*.py` | MDO 指令集结构与 SCPI 组装、通信重试、无效值 |
| `test_config_validation.py` / `test_all_configs.py` | 配置结构校验（加载与测试共用） |
| `test_auto_detect.py` / `test_device_identity.py` | 自动匹配与执行前身份核对 |
| `test_storage.py` / `test_report.py` / `test_cli_calibrate.py` | 原子保存、报告列与精度、CLI 流程 |
| `test_verification.py` | 验证台账：状态取值、verified 必须带实测信息 |

### 9.3 CI

`.github/workflows/ci.yml` 在 Ubuntu + Python 3.10/3.11/3.12/3.13 上依次执行
`ruff check` → `ruff format --check` → `mypy` → `pytest`。

> 受限沙箱下跑 `pytest` 时，使用 `tmp_path` 的用例可能因临时目录权限报 `PermissionError`；
> 那是环境限制，正常终端不受影响。

## 10. 已知限制

- **波形读回只支持 pyvisa**（`--socket-osc` 下 ENOB、直流偏置、时基拟合法、随机噪声不可用）；
- **9500B 不能输出 0 V**（`SOUR:VOLT 0` 与 0.5 mV 都会被静默丢弃，最小约 1 mV），零点用 ±1 mV 两点插值；
- **随机噪声需人工接 50 Ω 匹配负载**，程序会暂停等待确认；
- **不含测量不确定度**，不能直接作为校准证书的完整结果；
- **其他品牌/型号没有 v0.2.0 profile**，`commands/` 中的遗留指令集不能执行；
- **上升时间重复性最弱**：单次采集散布约 ±52 ps，已用 10 次平均降到约 ±17 ps；
- **时基频率法受示波器频率读数位数限制**（约百~千 ppm），精测以拟合为准；
- 指令集缺少某项可选 action 时，对应设置会被跳过而不报错（执行前能力完整性检查尚未接入）；
- MDO3052 只有 2 个模拟通道；水平档位为 1-2-4-8 量化序列、垂直档位为 1-2-5，
  请求不存在的档位会被吸附，记录里保存的是回读的实际值；
- 记录中的 `metadata.skipped_points` 目前只在 JSON 中，`show` 与 Excel 不展示（后续版本补充）。

## 11. 版本与兼容性

- **v0.2.0**：按 JJF 1057-2026 重建。项目集、点表、记录字段、报告表名全部换新；
  旧项目（`amp`、`delta_time`、`bandwidth`、`transient`）与旧 profile 已删除，
  **不保留别名、不做回退**。
- **V0.1.0（标签）**：旧版本行为，需要旧口径时 `git checkout V0.1.0`。
- 旧 JSON 记录仍能被 v0.2.0 读取，但其中的旧项目名不在 `ITEM_CONFIGS` 里，
  `show`/`export` 会跳过并提示"未知校准项目"；要看完整旧记录请检出 `V0.1.0`。
- 记录字段与报告表名在 v0.2.0 全部换新；后续小版本升级也暂不承诺记录格式向前兼容。

## License

MIT
