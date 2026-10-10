import math
import time

from rich.console import Console

from osccal.core import scpi_trace
from osccal.core.command import assemble_cmd

console = Console()

# 无效测量值标记：优利德 UPO1000X 等机型手册规定"返回数据为无效数据均用 * 表示"。
# 读数在刚改过挡位/触发/垂直位置时可能短暂无效，故查询失败前先重试。
INVALID_VALUE_MARKER = "*"
INVALID_VALUE_RETRIES = 2

# 写入间隔（秒）：少数机型在背靠背连续写入时会静默丢弃指令（错误队列仍为 "No error"），
# 实测优利德 UPO1104X 会出现，故由指令集 feature.write_delay_ms 声明所需间隔。
# 0 表示不节流（默认，且不影响既有各机型的时序）。
_write_delay: float = 0.0


def set_write_delay(milliseconds: object) -> None:
    """设置每条 SCPI 写入之后的最小间隔（毫秒）；非法值或 <=0 表示不节流。"""
    global _write_delay
    try:
        value = float(milliseconds)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        value = 0.0
    _write_delay = value / 1000.0 if value > 0 else 0.0


def write_delay() -> float:
    """当前写入间隔（秒）。"""
    return _write_delay


class ScpiError(RuntimeError):
    """通信或测量失败，禁止将失败响应作为校准数值使用。"""


def _socket_read_response(sock, max_bytes: int = 65536) -> str:
    """循环读取 Socket 响应直到换行或达到上限，避免单次 recv 截断长响应。

    读取超时不做吞掉处理，直接向上抛出 TimeoutError，由 _retry_query_or_write
    统一重试；否则超时会被当成"空响应"而永不重试。
    """
    data = b""
    while b"\n" not in data and len(data) < max_bytes:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    return data.decode(errors="replace")


def _is_timeout(exc: BaseException) -> bool:
    """识别超时异常：Python 层 TimeoutError，以及 pyvisa 的 VI_ERROR_TMO。"""
    if isinstance(exc, TimeoutError):
        return True
    return "timeout" in str(exc).lower()


def _retry_query_or_write(inst, cmd: str, comm_type: str, is_query: bool) -> str:
    action = "查询" if is_query else "写入"
    if not cmd or comm_type not in {"pyvisa", "socket"}:
        scpi_trace.record_failure()
        raise ScpiError(f"SCPI 指令为空或通信类型无效: {comm_type}")
    for attempt in range(2):
        try:
            if comm_type == "pyvisa":
                result = inst.query(cmd) if is_query else (inst.write(cmd) or "")
            else:
                inst.sendall(cmd.encode() + b"\n")
                result = _socket_read_response(inst) if is_query else ""
            scpi_trace.log_entry("Q" if is_query else "W", cmd, str(result))
            # 写入后按指令集声明的间隔节流，避免示波器静默丢弃背靠背指令
            if not is_query and _write_delay > 0:
                time.sleep(_write_delay)
            return result
        except Exception as e:
            if attempt == 0:
                time.sleep(0.5)
                continue
            if _is_timeout(e):
                console.print(f"[red]✗[/red] SCPI {action}超时 ({cmd})")
            else:
                console.print(f"[red]✗[/red] SCPI {action}失败 ({cmd}): {e}")
            scpi_trace.record_failure()
            scpi_trace.log_entry("Q" if is_query else "W", cmd, "ERROR")
            raise ScpiError(f"SCPI {action}失败: {cmd}") from e
    raise AssertionError("通信重试未返回结果")


def scpi_query(inst, cmd: str, comm_type: str = "pyvisa") -> str:
    return _retry_query_or_write(inst, cmd, comm_type, is_query=True)


def scpi_write(inst, cmd: str, comm_type: str = "pyvisa") -> str:
    return _retry_query_or_write(inst, cmd, comm_type, is_query=False)


def scpi_setup_measurement(inst, cmd_osc: dict, channel: str, meas_keyword: str):
    feature = cmd_osc.get("feature", {})
    meas_mode = feature.get("meas", "split")
    comm_type = cmd_osc.get("type", "pyvisa")

    if meas_mode == "merge":
        if "set_meas_source" in cmd_osc.get("actions", {}):
            scpi_write(
                inst,
                assemble_cmd(cmd_osc["actions"]["set_meas_source"], channel),
                comm_type,
            )
        if "set_meas_type" in cmd_osc.get("actions", {}):
            scpi_write(
                inst,
                assemble_cmd(cmd_osc["actions"]["set_meas_type"], meas_keyword),
                comm_type,
            )
    elif meas_mode == "split":
        set_meas = feature.get("set_meas", "Channel")
        if set_meas == "Channel":
            if "set_meas_source" in cmd_osc.get("actions", {}):
                scpi_write(
                    inst,
                    assemble_cmd(cmd_osc["actions"]["set_meas_source"], channel),
                    comm_type,
                )
        elif set_meas == "ItemChannel":
            if meas_keyword == "VAVG" and "set_meas_vavg" in cmd_osc.get("actions", {}):
                scpi_write(
                    inst,
                    assemble_cmd(cmd_osc["actions"]["set_meas_vavg"], channel),
                    comm_type,
                )
            elif "set_meas_item_and_source" in cmd_osc.get("actions", {}):
                scpi_write(
                    inst,
                    assemble_cmd(
                        cmd_osc["actions"]["set_meas_item_and_source"],
                        meas_keyword,
                        channel,
                    ),
                    comm_type,
                )


def read_measurement(
    inst,
    cmd_template: dict,
    cmd_osc: dict,
    channel: str,
    meas_keyword: str,
) -> float:
    res = ""
    value = ""
    try:
        scpi_setup_measurement(inst, cmd_osc, channel, meas_keyword)

        # ZDS 系列 split 模式设置测量项后需短暂等待示波器计算
        feature = cmd_osc.get("feature", {})
        meas_mode = feature.get("meas", "split")
        if meas_mode == "split":
            time.sleep(0.3)  # 等测量结果稳定
        return_value_index = feature.get("return_value_index", 0)
        get_value_mode = feature.get("get_value", "ByItemAndSource")
        comm_type = cmd_osc.get("type", "pyvisa")

        def query_once() -> str:
            """按测量模式查询一次，返回原始响应。"""
            if meas_mode == "merge":
                if "get_value" in cmd_osc.get("actions", {}):
                    return scpi_query(
                        inst,
                        assemble_cmd(cmd_osc["actions"]["get_value"]),
                        comm_type,
                    )
                return ""
            if get_value_mode == "ByItem":
                if "get_value_from_item" in cmd_osc.get("actions", {}):
                    return scpi_query(
                        inst,
                        assemble_cmd(
                            cmd_osc["actions"]["get_value_from_item"],
                            meas_keyword,
                        ),
                        comm_type,
                    )
                return ""
            if meas_keyword == "VAVG" and "get_value_vavg" in cmd_osc.get("actions", {}):
                return scpi_query(
                    inst,
                    assemble_cmd(
                        cmd_osc["actions"]["get_value_vavg"],
                        channel,
                    ),
                    comm_type,
                )
            if "get_value_from_item_and_source" in cmd_osc.get("actions", {}):
                return scpi_query(
                    inst,
                    assemble_cmd(
                        cmd_osc["actions"]["get_value_from_item_and_source"],
                        meas_keyword,
                        channel,
                    ),
                    comm_type,
                )
            return ""

        # 部分机型（如优利德 UPO1000X）用 "*" 表示本次测量无效——手册原文："当返回
        # 数据为无效数据均用*表示"。刚改过挡位/触发电平/垂直位置时读数可能短暂无效，
        # 因此先重试几次；仍无效时给出可诊断的提示，而不是抛浮点转换异常。
        def extract_value(raw: str) -> str:
            """取响应中第 return_value_index 个字段；字段不足时返回空串。

            merge 模式下 return_value_index 为 1，而无效响应可能只有一个 "*"，
            直接下标会抛 IndexError 掩盖真实原因，故这里做安全取值。
            """
            parts = raw.split("\n")[0].split(" ")
            return parts[return_value_index] if return_value_index < len(parts) else ""

        invalid = False
        for attempt in range(INVALID_VALUE_RETRIES + 1):
            res = query_once()
            value = extract_value(res)
            # 无效标记可能整个响应就是 "*"，也可能是带表头响应的某个字段
            invalid = res.split("\n")[0].strip() == INVALID_VALUE_MARKER or (
                value.strip() == INVALID_VALUE_MARKER
            )
            if not invalid:
                break
            if attempt < INVALID_VALUE_RETRIES:
                time.sleep(0.5)
                scpi_setup_measurement(inst, cmd_osc, channel, meas_keyword)
        if invalid:
            raise ScpiError(
                f"示波器返回无效测量值 {INVALID_VALUE_MARKER}（测量项 {meas_keyword}）："
                "通常是没有有效采集——请检查挡位是否与信号匹配、波形是否超出屏幕、"
                "触发电平与信号连接是否正常"
            )

        measured = float(value)
        # ZDS 系列返回 3.40282e+38 表示 Invalid
        if not math.isfinite(measured) or abs(measured) > 1e30:
            raise ValueError(f"测量值无效: {value}")
        return measured
    except ScpiError:
        raise
    except (ValueError, IndexError) as e:
        scpi_trace.record_failure()
        console.print(f"[red]✗[/red] 测量值解析失败: {e} (原始响应: '{res}')")
        raise ScpiError(f"测量值解析失败，原始响应: {res!r}") from e
    except Exception as e:
        scpi_trace.record_failure()
        console.print(f"[red]✗[/red] 读取测量值失败: {e}")
        raise ScpiError("读取测量值失败") from e
