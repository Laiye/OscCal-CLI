from rich.console import Console

console = Console()


def validate_args(action: dict, *args) -> bool:
    expected = action.get("args_num", 0)
    if len(args) != expected:
        console.print(
            f"[red]✗[/red] 参数数量错误: 期望 {expected}, 实际 {len(args)}"
        )
        return False
    return True


def assemble_cmd(action: dict, *args) -> str:
    if not validate_args(action, *args):
        return ""
    commands = action.get("commands", [])
    args_list = list(args)
    parts = []
    for i, cmd_fragment in enumerate(commands):
        parts.append(str(cmd_fragment))
        if i < len(args_list):
            parts.append(str(args_list[i]))
    return "".join(parts)
