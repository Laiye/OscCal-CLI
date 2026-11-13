# OscCal-CLI

数字示波器自动校准命令行工具。通过 SCPI 同时控制 **Fluke 9500B 校准仪**与被校示波器，
按 **JJF 1057-2026《数字示波器校准规范》** 第 7 章逐项取点、测量并保存可追溯的
JSON 原始记录与 Excel 报告。

| 项 | 当前状态 |
|---|---|
| 版本 | **v0.3.2** |
| 依据规范 | JJF 1057-2026，2027-02-21 实施，复校间隔 12 个月 |
| 实机验证硬件 | Tektronix MDO3052 + Fluke 9500B（9530 头） |
| 实机验证 | 2026-11-09 单方法方案（分离阻抗点表）一次复跑 10/10 项；2026-11-05 试验方案全量 10/10 项，见 [`verification/jjf1057_2026.json`](verification/jjf1057_2026.json) |
| 结论口径 | 规范表 1 明确"技术指标仅供参考，不作为符合性判定依据"；程序**不出具合格/不合格结论** |

---

## 1. 配置模型：特征 / 规范 / 方案

v0.3.0 起把"仪器事实、标准要求、本轮做法"彻底分开：

| 目录 | 回答的问题 | 只写什么 | 不写什么 |
|---|---|---|---|
| [`characteristics/`](characteristics) | 仪器是什么？ | 通道数、格线、垂直/水平档位集合、标称带宽、最高采样率、是否有 50 Ω、50 Ω 最高垂直挡位 | 校准点、方法、限值 |
| [`specs/`](specs) | 标准要求什么？ | 条款号、记录表号与字段、计算公式、`reference_limits`、偏离声明、环境 | 方法选择、取点参数、硬件能力 |
| [`schemes/`](schemes) | 本轮怎么做？ | 每个项目的 `methods` 候选集、`method` 实际执行方法、`primary`、`points`、`stimulus`、人工确认提示 | 参考限值、硬件档位全集 |
| [`commands/`](commands) | 怎么和这台仪器说话？ | SCPI 动作模板、测量助记符、机型能力声明 | 硬件事实、校准点 |
| [`calibrators/`](calibrators) | 标准器能输出什么？ | 探头、阻抗规则、输出上下限、SCPI 动作 | 被校设备信息、方案 |

解析流程完全离线：

```text
scheme（方法 + 取点） ┐
spec（条款 + 参考指标）├→ core/points.py → plan → runner
characteristics（能力）│
calibrators（输出能力）┘
```

- 方案未选的方法**不发送采集指令**，记录字段为 `null`，报告显示"不适用"；
- 机型没有的档位、标准器超限的点写入 `skipped` 并说明原因，**不静默降级**；
- 方案可以跨机型复用：同一套点表在 350 MHz / 500 MHz 机型上会自动过滤不可执行的点。

旧的 `profiles/` 目录与 `--profile` / `--spec` 参数在 v0.3.0 中已删除，旧 JSON 布局不再兼容。

### 1.1 试验方案与单方法方案

`schemes/` 下有两套方案：

| 方案 | 文件 | 用途 | 多方法项目 |
|---|---|---|---|
| 试验方案 | [`jjf1057_2026.json`](schemes/jjf1057_2026.json) | 方法比对、看方法间偏差，**不作为默认校准方案** | 全部方法并列执行 |
| 单方法方案 | [`jjf1057_2026_single.json`](schemes/jjf1057_2026_single.json) | **实际校准默认方案** | 每个项目只执行 `method` 指定的一种 |

多方法项目在方案里这样写：

```json
"dc_gain": {
  "methods": ["square_amplitude", "dc_two_point", "multi_point_lsq"],
  "method": "dc_two_point"
}
```

- `methods`：本方案声明可用的方法集合；
- `method`：实际执行的方法，必须属于 `methods`；设置后不再写 `primary`；
- `primary`：仅在试验方案（没有 `method`、跑全部方法）中用于报告主记录值；
- 单方法项目不需要 `method`。

当前单方法方案的选择：

| 项目 | 实际执行 |
|---|---|
| `dc_gain` | `dc_two_point`（直流两点法） |
| `dc_offset` | `raw_lsq`（原始码值拟合） |
| `timebase_error` | `waveform_fit`（波形拟合法） |

未选方法的采集指令不会发送；单方法执行时报告只保留该方法真正产生的列，不再同时出现
“方法一/主记录”两列，表头也不使用“主方法”。

---

## 2. 支持范围

### 2.1 硬件

| 角色 | 型号 | 说明 |
|---|---|---|
| 被校示波器 | Tektronix **MDO3052**（500 MHz，2 通道） | 已实机验证 |
| 被校示波器 | Tektronix **MDO3032**（350 MHz，2 通道） | 有特征文件，**验证台账未覆盖** |
| 标准器 | Fluke **9500B**（GPIB/USB） | 已实机验证 |
| 有源探头 | **9530**（600 MHz，边沿 150 ps / 500 ps） | 已实机验证，10 项全部使用 |
| 有源探头 | 9550（25 ps）、9560（6.4 GHz，70 ps） | 配置已声明，未实机验证 |

`commands/` 只保留 `tektronix_mdo.json`（MDO3052/3032 使用）与
`tektronix_mdo3.json`（3 Series MDO 方言，暂无特征文件）。

### 2.2 校准项目

JJF 1057-2026 第 7 章的 10 个项目全部实现：

| 项目键 | 条款 | 项目 | 实际执行方法（单方法方案） | 取点策略 | MDO3052 单通道点数 |
|---|---|---|---|---|---|
| `input_impedance` | 7.3.1 | 输入阻抗 | 校准仪负载测量 | 每通道 × 每阻抗状态 | 2 |
| `dc_gain` | 7.4.1 / 7.4.2 / 7.4.3 | 直流增益 | 直流两点法（试验：三法并列） | 垂直档位列表 × 1 MΩ/50 Ω | 6 |
| `dc_offset` | 7.5.1 / 7.5.2 | 直流偏置 | 原始码值拟合（试验：两法并列） | 垂直档位列表 × 1 MΩ/50 Ω | 6 |
| `freq_response_bandwidth` | 7.6 | 频率响应、频带宽度 | 正弦扫频 + 半功率点 | 相对标称带宽的比值频点 × 1 MΩ/50 Ω | 18 |
| `enob` | 7.7 | 动态有效位数 | 时域四参数拟合 | 现场按公式反推 × 1 MΩ/50 Ω | 2 |
| `rise_time` | 7.8 | 上升时间 | 快沿 10%~90% | 每通道 × 最快边沿档（150 ps） | 1 |
| `timebase_error` | 7.9.1 / 7.9.2 | 时基（采集速率）误差 | 波形拟合法（试验：两法并列） | 水平档位列表 | 3 |
| `delta_v` | 7.11 | ΔV（幅度）测量 | 自动幅度测量 | 垂直档位列表 × 1 MΩ/50 Ω | 5 |
| `delta_t` | 7.12 | Δt（时间）测量 | 自动周期测量 | 水平档位列表（MARK 时标） | 3 |
| `random_noise` | 7.13 | 随机噪声 | 采样标准差 | 固定条件（最小量程） | 1 |

合计 **47 点/通道**（MDO3052 + 9500B/9530）。双通道方案共 94 点，跳过 2 处，
均为规范定为人工的 7.2、7.10；50 Ω 与 1 MΩ 点表分离后不再产生点级跳过：

- 1 MΩ：`dc_gain`/`dc_offset` 为 0.001/0.1/10 V/div，`delta_v` 为
  0.001/0.1/10 V/div；
- 50 Ω：`dc_gain`/`dc_offset` 为 0.001/0.1/1 V/div（最高 1 V/div），
  `delta_v` 为 0.001/0.5 V/div（0.5 V/div 的 3.2 Vpp 在 9500B 5 Vpp 上限内）；
- 上升时间只取 9500B 9530 最快档 150 ps；500 ps 与 500 MHz 示波器上升时间同量级，
  会把标准源沿算进去，不作为校准点；
- `freq_response_bandwidth`、`enob` 的 1 MΩ/50 Ω 块当前参数相同，后续可分别调整；
- Δt 使用 9500B MARK 时标输出（约 9.0091 ns~55 s），10 ns/10 µs/10 ms 三档均可测。

50 Ω 输入最高 1 V/div 仍由 `characteristics.max_vertical_scale_50` 校验；
如果显式点表误写了不支持的挡位，`osccal plan` 仍会跳过并说明原因。

### 2.3 程序不做的事

- 不做合格判定，不输出"超差/合格"字样；
- 不评定测量不确定度（按规范偏离声明，由实验室依 JJF 1059.1 另行评定）；
- 不自动接匹配负载（随机噪声项暂停并提示人工确认）；
- 不实现 7.2 外观检查、7.10 自校准信号（需要人工或额外标准器）。

---

## 3. 安装

### 3.1 环境

- Python ≥ 3.10（CI 覆盖 3.10–3.13）；
- 与仪器通信的 VISA 运行时（如 NI-VISA）用于 USB / GPIB；Socket 连接不需要 VISA；
- 依赖：click、rich、PyVISA、PyVISA-py、openpyxl。

### 3.2 创建虚拟环境

```bash
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# Linux / macOS
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -e ".[dev]"
```

PowerShell 提示"禁止运行脚本"时，先执行
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`（仅当前窗口生效）。

### 3.3 验证安装

```bash
pip show osccal                 # Editable project location 应指向本仓库
where.exe osccal                # Windows；Linux/macOS 用 which
osccal --version                # osccal, version 0.3.1
```

> 仅看 `osccal --version` 不足以证明装对：激活虚拟环境只是把 `.venv\Scripts`
> 插到 PATH 最前，系统里若已装过 `osccal` 仍可能被执行。以 `pip show osccal`
> 的 Editable 路径为准。

### 3.4 输出编码

程序启动时把 stdout/stderr 切到 UTF-8，重定向到文件或管道不会再因 GBK 无法表示
`✓`/`Δ`/表格边框而报 `UnicodeEncodeError`。如需覆盖，设置环境变量 `PYTHONIOENCODING`。

---

## 4. 快速开始

```bash
# 1) 看设备
osccal device list

# 2) 离线核对方案的点表（不连仪器）
osccal plan --scheme jjf1057_2026_single --characteristics tektronix_mdo3052 --probe 9530 --channel 1,2

# 3) 自动识别设备并校准（--scheme 默认 jjf1057_2026_single，可省略）
osccal calibrate --auto --probe 9530

# 4) 查看 / 导出
osccal show --latest
osccal export
```

`calibrate --auto` 的顺序：

```text
扫描/指定 VISA 资源 → *IDN? 识别 → 匹配 commands + characteristics + calibrator
→ 查询已装探头（ROUT:FITT?）→ 打印识别结果并确认
→ 设备身份核对 → 按 scheme + spec + characteristics 解析点表
→ 逐项执行 → 每项结束原子保存记录
```

多通道时，切换到下一个通道前会暂停，等待把探头接到对应通道后按回车。

---

## 5. 命令参考

### 5.1 `osccal calibrate`

```bash
osccal calibrate [OPTIONS]
```

| 选项 | 说明 |
|---|---|
| `--auto` | 扫描 VISA 资源，按 `*IDN?` 自动识别设备并匹配配置 |
| `--osc PATH` | 示波器指令集文件（默认交互选择） |
| `--characteristics NAME 或 PATH` | 仪器特征：`characteristics/` 下名称（可省 `.json`）或文件路径（默认交互选择） |
| `--scheme NAME 或 PATH` | 校准方案：`schemes/` 下名称（可省 `.json`）或文件路径，默认 `jjf1057_2026_single`（实际校准）；方法比对用 `jjf1057_2026`（试验） |
| `--calibrator PATH` | 校准仪配置（默认取目录中首个） |
| `--channel 1,2` | 通道，逗号分隔（MDO3052 共 2 通道） |
| `--probe 9530 / 9550 / 9560` | 有源探头型号；`--auto` 下省略则自动识别 |
| `--items a,b` | 校准项目键，逗号分隔；`all` 表示方案中所有已实现项目 |
| `--resource-osc` / `--resource-cal` | 指定 VISA 资源地址 |
| `--socket-osc host:port` | 示波器走 Socket 连接（仅标量测量项可用） |
| `--log-scpi` | 退出前打印完整 SCPI 指令日志与失败统计 |

示例：

```bash
# 自动识别并实际校准（默认单方法方案）
osccal calibrate --auto --probe 9530

# 方法比对：显式选择试验方案（全部方法并列）
osccal calibrate --auto --probe 9530 --scheme jjf1057_2026

# 只跑直流类两项
osccal calibrate --auto --probe 9530 --channel 1 --items dc_gain,dc_offset

# 手动指定全部配置与资源
osccal calibrate \
  --osc commands/tektronix_mdo.json \
  --characteristics characteristics/tektronix_mdo3052.json \
  --scheme jjf1057_2026_single \
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

单项失败不会终止后续项目：失败项目记为 `failed`，已测到的数据点保留在 JSON 中
便于诊断，但 `show` / Excel 不展示；后续项目继续执行，本轮状态为
`completed_with_errors`。用户中断或"无法关闭校准仪输出"时立即终止本轮。

### 5.2 `osccal plan`

只解析点表，**不连接任何仪器**：

```bash
osccal plan --scheme jjf1057_2026_single --characteristics tektronix_mdo3052 --probe 9530 --channel 1,2
osccal plan --scheme jjf1057_2026            # 试验方案，多方法并列
osccal plan --json data/plan.json
```

输出每个项目的条款、所选方法、取点策略、点数、跳过数，并逐条打印跳过原因。
解析输入为 `schemes/`（方法与点）+ `specs/`（规范要求）+ `characteristics/`
（硬件特征）+ `calibrators/`（标准器能力）。

### 5.3 `osccal show`

```bash
osccal show --latest
osccal show --file data/calibration_xxx.json
osccal show                                # 交互选择
```

按项目输出表格（表名沿用规范附录 A 的记录表号），表尾打印参考指标、
依据规范/方案与偏离声明。

### 5.4 `osccal export`

```bash
osccal export                              # 最近一次 → 同目录同名 .xlsx
osccal export --file data/xxx.json --output report.xlsx
```

- 每个校准项目一张工作表，表名用规范附录 A 的编号与名称（如 `A.3 直流增益`）；
- 同一项目的多个通道合并到同一张表；
- 单元格按与 `show` 相同的显示精度舍入，仍是数值单元格；
- 首张"校准信息"表记录时间、状态、设备身份、依据规范/方案（含 sha256）、
  逐项方法选择与偏离声明；
- 表尾给出参考指标文本与免责说明，**不做合格/超差判定**。

### 5.5 `osccal device`

```bash
osccal device list
osccal device info --resource "GPIB0::19::INSTR"
osccal device info --socket 192.168.1.100:5025
```

---

## 6. 方法与测量口径

### 6.1 方案与方法选择

单方法方案用 `method` 指定实际执行的方法，`methods` 只作为候选集：

```json
"dc_gain": {
  "methods": ["square_amplitude", "dc_two_point", "multi_point_lsq"],
  "method": "dc_two_point"
}
```

试验方案不写 `method`，跑 `methods` 中全部方法，用 `primary` 指定报告主记录值：

```json
"dc_gain": {
  "methods": ["square_amplitude", "dc_two_point", "multi_point_lsq"],
  "primary": "square_amplitude"
}
```

- 有 `method` 时不再允许 `primary`；`method` 同时决定报告主记录值；
- 未选的方法不发送采集指令、不产生读数，记录字段为 `null`；
- 记录中保存 `metadata.scheme.items.<项目>.method`、`methods_selected` 与
  `primary_method`，报告信息页写明依据方案；
- 单方法项目也显式写 `methods`，便于核对"项目—方法"对应关系；
- 请求未实现的方法（如随机噪声的 RMS 读数法）在加载方案时直接报错。

### 6.2 各项目实现

| 项目 | 激励 | 读数与算法 |
|---|---|---|
| 输入阻抗 | 9500B 有源头 `CONF:RES` / `CONF:CAP` | 读校准仪的电阻/电容，与标称值比较；`2E35` 判为无效 |
| 直流增益 | DC / 1 kHz 对称方波 | 方法一（7.4.1）屏 90%/10% 两点；方法二（7.4.2）方波幅度 `G=Vr/V`；方法三（7.4.3）16 点最小二乘，同时给截距 |
| 直流偏置 | DC，偏置 0 与 2 格；1 MΩ / 50 Ω | 方法二按 7.5.2：原始码值 `(码值−YOFf)×YMUlt`（不叠加 YZEro）扫 16 点拟合，`d_c=−b`；方法一按 7.5.1 两点（激励取与 d₀ 同号） |
| 频率响应 | 正弦 0.5 Vpp；1 MΩ / 50 Ω | 以 50 kHz 为基准，`G=Vk/V0`；相邻频点间按对数频率插值求 0.707 |
| ENOB | 正弦，峰值约 95% 量程；1 MΩ / 50 Ω | 采样率现场读回，`f=fs·n/N`（N=1000、n=7 互质），附录 E 四参数拟合，`ENOB=log2(V0/(√12·Er))` |
| 上升时间 | 快沿，匹配阻抗（50 Ω） | `RIS` 测量项读 10%~90% 过渡时间，10 次独立采集平均，同时记录正过冲与标准差 |
| 时基误差 | 正弦 | 方法一（7.9.1）频率读数 `δT=(f_std−f_read)/f_std`；方法二（7.9.2）波形拟合 `δT=f_std/f_app−1`；并校验拟合频率与读数一致（>5% 判时间轴不可信） |
| ΔV | 1 kHz 对称方波；1 MΩ / 50 Ω | 自动幅度测量读数代替光标，误差相对标准值 |
| Δt | 1 kHz 对称方波 | 周期测量 ×M（M=2）与标准值比较 |
| 随机噪声 | 输入端接 50 Ω 匹配负载（人工确认） | 最小量程、最高采样率下取 1000 点波形求标准差，占满量程百分比 |

### 6.3 公共约定

- **每次读数前重新采集**，并用 `ACQuire:STATE?` 轮询确认采集结束，避免读到陈旧值；
- **直流/无沿信号自由运行**，不走"单次采集等触发"（等不到触发会白等 5 s）；
- **读数收敛判据**：标准源换函数后幅度约 2 s 才建立，标量读数按"间隔 0.5 s 连读、
  相对差 ≤0.1%"判定收敛；直流扫描点用固定建立时间；
- **记录长度 = 分析点数**（ENOB、拟合、偏置），且在采集之前固定，否则数据与
  `XINcr` 不匹配；
- **阻抗两端一起设并回读校验**：50 Ω 输出接 1 MΩ 输入会让读数翻倍；
  只有特征文件声明 `imp_has_50` 的机型才生成 50 Ω 点，超出 9500B 输出上限的点进入 `skipped`。
  切 50 Ω 前先把校准仪幅度降到 0.1 V：9500B 在高幅度（如 64 Vpp）下会拒绝切换，
  查询会持续返回 1E6，容易误判为阻抗失配；
- **无效读数重新采集**：泰克 `9.9E+37`、优利德 `*`、ZDS `3.4E+38` 都表示本次测量无效，
  `base._read_meas` 会在 `InvalidMeasurementError` 时重新采集（最多 3 次）；
- **方波方法先跑**：先跑直流类方法再测方波幅度，读数会系统性偏高 1.9%~5.0%。

### 6.4 已知与规范的偏离

写入记录 `metadata.spec.deviations`：

1. ΔV、Δt 用示波器自动测量读数代替 7.11/7.12 要求的"移动测量光标读数"；
2. 本记录不包含测量不确定度，由实验室按 JJF 1059.1 另行评定；
3. 7.13 随机噪声为人工确认环节，程序暂停并提示接入匹配负载。

实现约定（规范未逐字规定、以实机可行性为准）：

- 直流偏置方法一的激励取与 d₀ **同号**（规范原文为 −d₀，取负号会把波形推出屏幕）；
- 零点测量用 **±1 mV 两点插值**：9500B 的 `SOUR:VOLT 0` 会被静默丢弃（最小约 1 mV）；
- 上升时间按图 9 接匹配阻抗：机型有 50 Ω 输入时用 50 Ω，没有时退为 1 MΩ 并注明；
- 直流偏置误差按 `δd = d_r − d₀` 记录（与 `offset_error_v` 字段同号）。

> 参考指标来自规范表 1，只作参照；终端与 Excel 均不给出合格/不合格结论。
> 参考指标文本由记录里的 `metadata.limits`（取自 `specs/*.json:reference_limits`）渲染。

---

## 7. 实机验证

验证条件：MDO3052（SN C020687，FW CF:91.1CT FV:v1.30）+ 9500B（SN 045029，
FW 4.11，9530 头 SN 882750012，证书 WWM202600225，检定日期 2026-03-03；
快沿 146 ps、主输出上升时间 409 ps）。

| 项目 | 状态 | 关键结果（2026-11-09 分离阻抗点表复跑 10 项） |
|---|---|---|
| 输入阻抗 | verified | 1 MΩ：−0.160%；50 Ω：+0.066% |
| 直流增益 | verified | 直流两点法 7 点：0.194~0.410%；50 Ω 1 V/div +0.194% |
| 直流偏置 | deviation | 原始码值拟合 7 点：零点 −1.69~+43.70 mV；Δd −32.45~−0.17 mV；最差 0.574% FS（50 Ω 0.01 V/div） |
| 频率响应 | verified_with_caveat | 500 MHz 处 1 MΩ G=0.740、50 Ω G=0.803；两种阻抗均 ≥0.707 → 带宽 ≥500 MHz；带内最大约 +1.6% |
| 动态有效位数 | verified_with_caveat | 2.5 GS/s、17.5 MHz、1.52 Vpp 下 1 MΩ 6.20 bit / 50 Ω 6.23 bit |
| 上升时间 | verified_with_caveat | 150 ps 边沿 802.1 ps；500 ps 边沿 865.2 ps；差 63.14±23.0 ps |
| 时基误差 | verified_with_caveat | 波形拟合法 +18.0 ~ −303.0 ppm（3 档）；频率法未执行（单方法方案） |
| ΔV | deviation | 1 MΩ 4 点 0.000%；50 Ω 0.01 V/div −0.625%，50 Ω 0.1 V/div 0.000% |
| Δt | deviation | MARK 时标 3 档：−0.008~0.000%（10 ns/div −0.008%） |
| 随机噪声 | verified_with_caveat | 0.163 mV = 2.0360% FS（50 Ω 负载，1 mV/div 本底） |

`verified_with_caveat` 表示测量完成但存在需注明的限制（分辨率、重复性、外部条件）；
`deviation` 表示与规范方法存在偏离，已在 `deviations` 中声明。状态描述的是
**测量是否完成且可信**，不是合格判定。逐项限制与记录文件见
[`verification/jjf1057_2026.json`](verification/jjf1057_2026.json)。

**单方法方案复跑（2026-11-09，分离阻抗点表）**

- 方案：`jjf1057_2026_single`；通道 CH1；10 项全部完成且无失败；SCPI 错误 0；
- 记录：`data/calibration_20261109_094459_209593_a696b00142ff40fbbc98af4d7e8138f9.json`
  （一次会话，含随机噪声；执行前已接 50 Ω 负载）；
- 点表：51 点/通道，点级跳过 0 处（50 Ω 与 1 MΩ 已分开列点；另有 2 项人工项）；
- 直流增益 50 Ω 1 V/div（±3.2 V 直流）误差 +0.194%；
- Δt 使用 9500B MARK 时标，10 ns/10 µs/10 ms 三档全部可测，误差 −0.008~0.000%；
- 随机噪声 0.163 mV = 2.0360% FS（50 Ω 负载，1 mV/div 本底）。

> 2026-11-09 的 10 项分离阻抗点表记录已写入验证台账。

---

## 8. 记录与报告

### 8.1 文件位置

`data/calibration_<YYYYmmdd_HHMMSS_微秒>_<uuid>.json`（`data/` 已被 gitignore）。
同一轮校准从开始到结束只写同一个文件：先写同目录临时文件、`fsync`、再 `os.replace`
原子替换，写入失败不会破坏上一份完整记录。

### 8.2 记录结构

```jsonc
{
  "metadata": {
    "timestamp": "...", "status": "completed|completed_with_errors|interrupted|failed",
    "channel": "1", "probe": "9530",
    "oscilloscope": {"manufacturer": "...", "model": "...", "serial": "...", "firmware": "..."},
    "calibrator":   {"manufacturer": "...", "model": "...", "serial": "...", "firmware": "..."},
    "commands_file": "...", "characteristics_file": "...", "calibrator_file": "...",
    "spec": {"spec_code": "JJF 1057-2026", "file": "...", "sha256": "...",
             "deviations": [...], "limits_semantics": {...}},
    "scheme": {"name": "JJF 1057-2026 默认校准方案", "file": "...", "sha256": "...",
               "items": {"dc_gain": {"methods": ["square_amplitude", "..."], "primary": "..."}}},
    "points_plan": {"1": {"dc_gain": 6, "...": 0}},
    "skipped_points": [{"item": "Δt（时间）测量", "reason": "..."}],
    "requested_items": [...], "item_status": {"dc_gain": "failed", "delta_v": "completed"},
    "failures": {"dc_gain": {"type": "ScpiError", "message": "..."}},
    "error": {"type": "...", "message": "..."},
    "scpi_errors": 0,
    "configurations": {"commands": {"sha256": "...", "data": {...}}, "characteristics": {...},
                       "calibrator": {...}, "scheme": {...}}
  },
  "results": {
    "dc_gain": [ {"index": 1, "channel": "1", "gain": 1.0012, "methods_selected": [...], "..." : "..."} ]
  }
}
```

- 多通道时结果键为 `<item>_ch<通道>`；
- 原始读数（未舍入）只保存在这里，终端与 Excel 显示按精度舍入后的值；
- `metadata.item_status` 逐项记录 `completed` / `failed`；失败项目的已测点保留在
  `results` 中，但 `show` / Excel 会跳过该项，失败原因在 `metadata.failures`；
- `metadata.configurations` 保存本次实际使用的指令集 / 特征 / 校准仪 / 方案副本与
  sha256，配置文件事后被修改也能追溯。

### 8.3 精度与显示

列定义与显示精度只有一份声明：`osccal/core/table_configs.py` 的 `ITEM_CONFIGS`
与 `ITEM_PRECISION`。终端 `show` 与 Excel 导出共用 `core/utils.py` 的格式化函数，
新增/删除列时两处自动一致（`tests/test_report.py` 守护列数与精度数量一致）。

单方法方案下，报告会按结果行/方案中的 `method` **自动删除未选方法的方法列**
（`active_config()`），表格下方输出“执行方法：…”。基础列已经承载判定值时，
方法专用列（如 `gain_m1`/`gain_m3`）和只对未选方法有意义的列（如方波法的
“被校示值 Vpp”）也一并删除，避免同一读数出现两列；多方法试验方案的基础列
表头改用“主记录增益/主记录误差”，不再出现“主方法”。终端 runner 的表格同样
只保留实际执行的方法列。频响/ENOB 表增加“挡位(V/div)”列，便于区分不同垂直
档位。参考指标文本用记录里的规范限值渲染，不在报告代码里另写一份限值。

---

## 9. 配置契约

### 9.1 目录

```text
osccal/
├── cli.py                    # 命令入口（calibrate / plan / show / export / device）
├── core/
│   ├── points.py             # 点表解析：scheme + spec + characteristics + calibrator
│   ├── methods.py            # 方法键、中文名、短标签、方法实际波形
│   ├── config.py             # JSON 加载（加载即校验）
│   ├── config_validation.py  # 唯一的配置结构校验实现
│   ├── comm.py               # SCPI 读写/重试/二进制块读取/无效值处理
│   ├── connect.py            # VISA / Socket 连接与设备释放
│   ├── command.py            # 命令模板组装
│   ├── waveform.py           # 前导信息与 IEEE 488.2 块解析
│   ├── fitting.py            # 正弦四参数最小二乘（附录 E）
│   ├── storage.py            # 记录原子保存 / 配置快照 / 状态
│   ├── export.py             # Excel 报告
│   ├── table_configs.py      # 终端与 Excel 的列/精度/参考指标
│   ├── auto_detect.py        # --auto 设备与配置匹配
│   ├── scpi_trace.py         # SCPI 日志与失败计数
│   ├── types.py              # TypedDict 配置类型
│   └── utils.py              # 编码、格式化、误差
└── measure/
    ├── base.py               # 连接、采集、读数收敛、波形读回、阻抗、表格
    ├── registry.py           # 项目清单 + 执行顺序 + RUNNERS
    ├── all.py                # 按序执行项目；单项失败不终止整轮
    └── <10 个项目>.py         # 每项一个 runner
specs/            # 规范要求
schemes/          # 校准方案
characteristics/  # 仪器特征
calibrators/      # 标准器能力
commands/         # SCPI 指令模板与能力声明
verification/     # 实机验证台账
tests/            # pytest
data/             # 运行产物（gitignore）
```

### 9.2 方案文件

```json
{
  "$schema": "osccal.scheme.v1",
  "name": "JJF 1057-2026 单方法校准方案",
  "description": "实际校准用：多方法项目只执行 method 指定的一种。",
  "spec": "jjf1057_2026",
  "items": {
    "dc_gain": {
      "methods": ["square_amplitude", "dc_two_point", "multi_point_lsq"],
      "method": "dc_two_point",
      "stimulus": {"shape": "SQU", "freq_hz": 1000, "polarity": "SYMM"},
      "points": {
        "strategy": "scale_list",
        "by_impedance": {
          "1M": {
            "scales_v_per_div": [0.01, 0.1, 1.0, 10.0],
            "screen_fraction": 0.8
          },
          "50": {
            "scales_v_per_div": [0.01, 0.1, 1.0],
            "screen_fraction": 0.8
          }
        }
      },
      "notes": ["方波只取 1 kHz：9500B 方波仅在 ≤10 kHz 有指标"]
    }
  }
}
```

- `spec` 指向 `specs/` 的文件名（不含 `.json`）；
- `points.by_impedance` 按 `"1M"`/`"50"` 分别写点表，键顺序即计划表顺序；
  与旧的 `points.impedances` **互斥**，旧 flat 写法仍兼容；
- 采用 `by_impedance` 时，每个阻抗块写清该阻抗的 `scales_v_per_div`（或频点、
  ENOB 参数）；`screen_fraction`、`offset_nominal_divisions` 等未写的参数可回退到
  顶层公共值；报告仍用“阻抗”列区分，不拆表；
- `methods` 只能取 [`osccal/core/methods.py`](osccal/core/methods.py) 中已实现的键；
- `method` 必须属于 `methods`，且与 `primary` 互斥；
- 试验方案（无 `method`）跑全部方法，`dc_gain` / `dc_offset` 必须给 `primary`；
- 单方法项目只有一个方法，不写 `method`；
- 方案未列入的项目在计划里为 `not_in_scheme`，不会被执行；
- 人工项（外观检查、自校准信号）留在规范里，不写入方案。

### 9.3 新增机型 / 新增方案

新增示波器：

1. 在 `commands/` 新建指令集：`manufacturer`/`models`/`series`、`feature`、
   `keyword`、`actions`。校验规则见 `config_validation.validate_commands`。
2. 在 `characteristics/` 新建特征文件：只写硬件事实，不含方法、点表与限值。
3. 用 `osccal plan --scheme jjf1057_2026_single --characteristics <名称或路径>` 核对点表；
   需要不同方法或点时，复制 `schemes/` 下的方案另存，保持 `spec` 指向同一规范。
4. 实机跑通全部项目，测得的点数、最大偏差、固件版本写入 `verification/*.json`。
5. 更新本文档的"支持范围"与"实机验证"两节。

> 版本号只有一处来源：`osccal/__init__.py:__version__`；`pyproject.toml` 用
> `dynamic = ["version"]` 引用它，不要在别处写死（`tests/test_specs.py` 守护）。

---

## 10. 开发与测试

### 10.1 质量门禁（与 CI 一致）

```bash
.venv\Scripts\ruff check .
.venv\Scripts\ruff format --check osccal tests
.venv\Scripts\mypy
.venv\Scripts\pytest
```

Linux/macOS 把 `.venv\Scripts\` 换成 `.venv/bin/`。
`mypy` 只检查 `pyproject.toml` 里列出的 4 个模块；`ruff format` 不覆盖
`commands/ characteristics/ specs/ schemes/ calibrators/`（JSON 目录）。

### 10.2 测试范围（约 541 个用例，以 CI 为准）

| 文件 | 覆盖 |
|---|---|
| `test_specs.py` | 规范契约、方案契约、版本号唯一来源 |
| `test_plan.py` | 点表解析、跳过原因、方法选择、方案未列项目 |
| `test_runners*.py` | 10 个项目 runner 的读数、算法、记录字段、方法裁剪 |
| `test_impedance.py` | 阻抗设置/回读校验、通道号传递、回读值解析 |
| `test_waveform.py` | 前导信息解析、块头/字节序/有符号解码、电压与时间轴 |
| `test_fitting.py` | 正弦拟合精度、异常输入、ENOB 公式 |
| `test_mdo3_*.py` | MDO 指令集结构、SCPI 组装、通信重试、无效值 |
| `test_config_validation.py` / `test_all_configs.py` | 五类配置结构校验与交叉引用 |
| `test_auto_detect.py` / `test_device_identity.py` | 自动匹配与执行前身份核对 |
| `test_storage.py` / `test_report.py` / `test_cli_calibrate.py` | 原子保存、报告列与精度、CLI 流程 |
| `test_verification.py` | 验证台账结构、状态取值、实测字段 |

### 10.3 CI

`.github/workflows/ci.yml` 在 Ubuntu + Python 3.10/3.11/3.12/3.13 上依次执行
`ruff check` → `ruff format --check` → `mypy` → `pytest`。

> 受限沙箱下跑 `pytest` 时，使用 `tmp_path` 的用例可能因临时目录权限报
> `PermissionError`；那是环境限制，正常终端不受影响。

---

## 11. 已知限制

- **波形读回只支持 pyvisa**（`--socket-osc` 下 ENOB、直流偏置、时基拟合法、随机噪声不可用）；
- **9500B 不能输出 0 V**（`SOUR:VOLT 0` 与 0.5 mV 都会被静默丢弃，最小约 1 mV），
  零点用 ±1 mV 两点插值；
- **随机噪声需人工接 50 Ω 匹配负载**，程序会暂停等待确认；
- **不含测量不确定度**，不能直接作为校准证书的完整结果；
- **MDO3032 只有特征文件与回归记录，没有独立验证台账**；其他品牌/型号需补
  `commands + characteristics` 并实机验证后才算支持；
- **方法裁剪不改变点数**：只选部分方法时执行时间减少，但点表仍按原档位生成；
  需要改点数请改方案的 `points`，不要改 runner；
- **上升时间重复性最弱**：单次采集散布约 ±45~62 ps，已用 10 次平均降低标准误；
- **时基频率法受示波器频率读数位数限制**（约百~千 ppm）；7.9.1 频率法与 7.9.2 拟合法
  并列记录、不指定唯一判定值；
- 指令集缺少某项可选 action 时，对应设置会被跳过而不报错；
- MDO3052 水平档位为 1-2-4-8 量化序列、垂直档位为 1-2-5，请求不存在的档位会被吸附，
  记录里保存的是回读的实际值；
- 记录中的 `metadata.skipped_points` 会显示在 `show` 的"跳过的校准点"表和 Excel
  校准信息表中。

---

## 12. 版本与兼容性

- **v0.3.2（2026-11-09）**：单方法方案的 `dc_gain` 改为 `dc_two_point`
  （直流两点法），50 Ω 1 V/div 进入点表；新增
  `characteristics.max_vertical_scale_50`（MDO 系列 1 V/div）；点表支持
  `points.by_impedance`，1 MΩ/50 Ω 分块配置；Δt 改用 9500B MARK 时标；单方法
  报告删除与方法专用列重复的列和只在方波法下有效的“被校示值 Vpp”，不再出现
  “方法一/主方法”并列表头。2026-11-09 在 MDO3052 上复跑 10 项。
- **v0.3.1**：新增“单方法校准方案” `jjf1057_2026_single.json` 并设为 CLI 默认；
  多方法项目用 `method` 键指定实际执行的一种（`dc_gain` 方波幅度法、
  `dc_offset` 原始码值拟合、`timebase_error` 波形拟合法）；原
  `jjf1057_2026.json` 降为试验/参考方案，保留全部方法并列。2026-11-06
  在 MDO3052 上完成三个多方法项目的单方法实机复测。
- **v0.3.0**：配置分层重构。`profiles/` 改名 `characteristics/`（只保留硬件特征），
  `specs/` 只保留规范要求，方法与取点迁入新的 `schemes/`；新增按项目选择已实现方法
  （`dc_gain` 三法、`dc_offset` 两法、`timebase_error` 两法）。CLI 改为
  `--scheme` / `--characteristics`，旧 `--spec` / `--profile` 与旧 JSON 布局不再兼容。
  2026-11-05 在 MDO3052 上按默认方案完成 10 项实机复核。
- **v0.2.1**：v0.2.0 的补丁版，记录格式保持兼容。包含 P0 修复（空跑、单项容错、NaN）、
  P1 口径完善（时基两法并列、直流增益收敛判据、报告方法列、参考指标单一来源）、
  P2 清理（删除模拟器与遗留指令集、死代码/废弃字段），并按当时代码完成 10 项实机复核。
- **v0.2.0**：按 JJF 1057-2026 重建。项目集、点表、记录字段、报告表名全部换新；
  旧项目（`amp`、`delta_time`、`bandwidth`、`transient`）与旧 profile 已删除，
  **不保留别名、不做回退**。
- **V0.1.0（标签）**：旧版本行为，需要旧口径时 `git checkout V0.1.0`。
- 旧 JSON 记录仍能被 v0.3.0 读取，但旧项目名不在 `ITEM_CONFIGS` 里，
  `show`/`export` 会跳过并提示"未知校准项目"；旧记录没有 `metadata.scheme`，
  终端与 Excel 不显示方案信息。
- v0.3.0 起小版本升级保持记录可读；报告列可能增补，旧字段不删除。

---

## License

MIT
