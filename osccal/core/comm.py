from rich.console import Console
import socket as sock
import time
from osccal.core.command import assemble_cmd

console = Console()


def _retry_query_or_write(inst, cmd: str, comm_type: str, is_query: bool) -> str:
    for attempt in range(2):
        try:
            if comm_type == "pyvisa":
                return inst.query(cmd) if is_query else (inst.write(cmd) or "")
            if comm_type == "socket":
                inst.send(cmd.encode() + b"\n")
                return inst.recv(4096).decode() if is_query else ""
            console.print(f"[red]✗[/red] 不支持的通信类型: {comm_type}")
            return ""
        except sock.timeout:
            if attempt == 0:
                time.sleep(0.5)
                continue
            console.print(f"[red]✗[/red] SCPI {'查询' if is_query else '写入'}超时 ({cmd})")
            return ""
        except Exception as e:
            if attempt == 0:
                time.sleep(0.5)
                continue
            console.print(f"[red]✗[/red] SCPI {'查询' if is_query else '写入'}失败 ({cmd}): {e}")
            return ""
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
            if "set_meas_item_and_source" in cmd_osc.get("actions", {}):
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

        feature = cmd_osc.get("feature", {})
        meas_mode = feature.get("meas", "split")
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
                if "get_value_from_item_and_source" in cmd_osc.get("actions", {}):
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

        return float(value)
    except (ValueError, IndexError) as e:
        console.print(f"[red]✗[/red] 测量值解析失败: {e} (原始响应: '{res}')")
        return 0.0
    except Exception as e:
        console.print(f"[red]✗[/red] 读取测量值失败: {e}")
        return 0.0
