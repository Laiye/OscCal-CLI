from rich.console import Console
from osccal.core.command import assemble_cmd

console = Console()


def scpi_query(inst, cmd: str, comm_type: str = "pyvisa") -> str:
    try:
        if comm_type == "pyvisa":
            return inst.query(cmd)
        if comm_type == "socket":
            inst.send(cmd.encode() + b"\n")
            return inst.recv(4096).decode()
        console.print(f"[red]✗[/red] 不支持的通信类型: {comm_type}")
        return ""
    except Exception as e:
        console.print(f"[red]✗[/red] SCPI 查询失败 ({cmd}): {e}")
        return ""


def scpi_write(inst, cmd: str, comm_type: str = "pyvisa") -> str:
    try:
        if comm_type == "pyvisa":
            inst.write(cmd)
            return ""
        if comm_type == "socket":
            inst.send(cmd.encode() + b"\n")
            return inst.recv(4096).decode()
        console.print(f"[red]✗[/red] 不支持的通信类型: {comm_type}")
        return ""
    except Exception as e:
        console.print(f"[red]✗[/red] SCPI 写入失败 ({cmd}): {e}")
        return ""


def read_measurement(
    inst,
    cmd_template: dict,
    cmd_osc: dict,
    channel: str,
    meas_keyword: str,
) -> float:
    try:
        feature = cmd_osc.get("feature", {})
        meas_mode = feature.get("meas", "split")
        return_value_index = feature.get("return_value_index", 0)
        get_value_mode = feature.get("get_value", "ByItemAndSource")
        res = ""
        value = ""

        if meas_mode == "merge":
            if "set_meas_source" in cmd_osc.get("actions", {}):
                scpi_write(
                    inst,
                    assemble_cmd(cmd_osc["actions"]["set_meas_source"], channel),
                    cmd_osc.get("type", "pyvisa"),
                )
            if "set_meas_type" in cmd_osc.get("actions", {}):
                scpi_write(
                    inst,
                    assemble_cmd(cmd_osc["actions"]["set_meas_type"], meas_keyword),
                    cmd_osc.get("type", "pyvisa"),
                )
            if "get_value" in cmd_osc.get("actions", {}):
                res = scpi_query(
                    inst,
                    assemble_cmd(cmd_osc["actions"]["get_value"]),
                    cmd_osc.get("type", "pyvisa"),
                )
            value = res.split("\n")[0].split(" ")[return_value_index]

        elif meas_mode == "split":
            set_meas = feature.get("set_meas", "Channel")
            if set_meas == "Channel":
                if "set_meas_source" in cmd_osc.get("actions", {}):
                    scpi_write(
                        inst,
                        assemble_cmd(cmd_osc["actions"]["set_meas_source"], channel),
                        cmd_osc.get("type", "pyvisa"),
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
                        cmd_osc.get("type", "pyvisa"),
                    )

            if get_value_mode == "ByItem":
                if "get_value_from_item" in cmd_osc.get("actions", {}):
                    res = scpi_query(
                        inst,
                        assemble_cmd(
                            cmd_osc["actions"]["get_value_from_item"],
                            meas_keyword,
                        ),
                        cmd_osc.get("type", "pyvisa"),
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
                        cmd_osc.get("type", "pyvisa"),
                    )

            value = res.split("\n")[0].split(" ")[return_value_index]

        return float(value)
    except (ValueError, IndexError) as e:
        console.print(f"[red]✗[/red] 测量值解析失败: {e} (原始响应: '{res}')")
        return 0.0
    except Exception as e:
        console.print(f"[red]✗[/red] 读取测量值失败: {e}")
        return 0.0
