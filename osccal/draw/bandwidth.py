import matplotlib.pyplot as plt


def draw_bandwidth(data: dict, channel: str, min_mhz: float = 100):
    if not data:
        return

    names = list(data.keys())
    values = list(data.values())

    fig, ax = plt.subplots()
    ax.set_title(f"Bandwidth - CH{channel}")
    ax.set_xlabel("Vertical deflection coefficient (V/Div)")
    ax.set_ylabel("Bandwidth (MHz)")
    ax.scatter(names, values, zorder=5)
    ax.plot(names, [min_mhz] * len(data), "r--", label=f"Min ({min_mhz} MHz)")
    ax.legend()
    plt.tight_layout()
    plt.show()
