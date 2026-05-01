import matplotlib.pyplot as plt


def draw_time(data: dict, channel: str, limits: dict = None):
    if not data:
        return

    names = list(data.keys())
    values = list(data.values())

    upper = limits.get("upper", 2.0) if limits else 2.0
    lower = limits.get("lower", -2.0) if limits else -2.0

    fig, ax = plt.subplots()
    ax.set_title(f"Δt(Time) - CH{channel}")
    ax.set_xlabel("Horizontal deflection coefficient (s/Div)")
    ax.set_ylabel("Relative error (%)")
    ax.scatter(names, values, zorder=5)
    ax.plot(names, [upper] * len(data), "r--", label=f"+{upper}%")
    ax.plot(names, [lower] * len(data), "r--", label=f"{lower}%")
    ax.axhline(y=0, color="gray", linestyle="-", linewidth=0.5)
    ax.legend()
    plt.tight_layout()
    plt.show()
