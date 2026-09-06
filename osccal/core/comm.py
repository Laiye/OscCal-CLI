import time

from rich.console import Console

from osccal.core import scpi_trace
from osccal.core.command import assemble_cmd

console = Console()


def _socket_read_response(sock, max_bytes: int = 65536) -> str:
    """循环读取 Socket 响应直到换行或达到上限，避免单次 recv 截断长响应。"""
    data = b""
    while b"\n" not in data and len(data) < max_bytes:
        try:
            chunk = sock.recv(4096)
        except sock.timeout:
            break
        if not chunk:
            break
        data += chunk
    return data.decode(errors="replace")


def _retry_query_or_write(inst, cmd: str, comm_type: str, is_query: bool) -> str:
    for attempt in range(2):
        try:
            if comm_type == "pyvisa":
                result = inst.query(cmd) if is_query else (inst.write(cmd) or "")
            elif comm_type == "socket":
                inst.send(cmd.encode() + b"\n")
                result = _socket_read_response(inst) if is_query else ""
            else:
                console.print(f"[red]✗[/red] 不支持的通信类型: {comm_type}")
                return ""
            scpi_trace.log_entry("Q" if is_query else "W", cmd, str(result))
            return result
        except TimeoutError:
            if attempt == 0:
                time.sleep(0.5)
                continue
            console.print(f"[red]✗[/red] SCPI {'查询' if is_query else '写入'}超时 ({cmd})")
        except Exception as e:
            if attempt == 0:
                time.sleep(0.5)
                continue
            console.print(f"[red]✗[/red] SCPI {'查询' if is_query else '写入'}失败 ({cmd}): {e}")
        scpi_trace.record_failure()
        scpi_trace.log_entry("Q" if is_query else "W", cmd, "ERROR")
    return ""


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
        res = ""
        value = ""

        if meas_mode == "merge":
            if "get_value" in cmd_osc.get("actions", {}):
                res = scpi_query(
                    inst,
                    assemble_cmd(cmd_osc["actions"]["get_value"]),
                    comm_type,
                )
            value = res.split("\n")[0].split(" ")[return_value_index]

        elif meas_mode == "split":
            if get_value_mode == "ByItem":
                if "get_value_from_item" in cmd_osc.get("actions", {}):
                    res = scpi_query(
                        inst,
                        assemble_cmd(
                            cmd_osc["actions"]["get_value_from_item"],
                            meas_keyword,
                        ),
                        comm_type,
                    )
            else:
                if meas_keyword == "VAVG" and "get_value_vavg" in cmd_osc.get("actions", {}):
                    res = scpi_query(
                        inst,
                        assemble_cmd(
                            cmd_osc["actions"]["get_value_vavg"],
                            channel,
                        ),
                        comm_type,
                    )
                elif "get_value_from_item_and_source" in cmd_osc.get("actions", {}):
                    res = scpi_query(
                        inst,
                        assemble_cmd(
                            cmd_osc["actions"]["get_value_from_item_and_source"],
                            meas_keyword,
                            channel,
                        ),
                        comm_type,
                    )

            value = res.split("\n")[0].split(" ")[return_value_index]

        measured = float(value)
        # ZDS 系列返回 3.40282e+38 表示 Invalid
        if measured > 1e30:
            console.print(
                f"[yellow]⚠[/yellow] 测量值异常 ({measured:.4g})，"
                f"可能是示波器不支持此测量项或信号条件不满足"
            )
            return 0.0
        return measured
    except (ValueError, IndexError) as e:
        console.print(f"[red]✗[/red] 测量值解析失败: {e} (原始响应: '{res}')")
        return 0.0
    except Exception as e:
        console.print(f"[red]✗[/red] 读取测量值失败: {e}")
        return 0.0
