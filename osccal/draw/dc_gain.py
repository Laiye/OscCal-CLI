import matplotlib.pyplot as plt


def draw_dc_gain(data: dict, channel: str, limits: dict = None):
    if not data:
        return

    upper = limits.get("upper", 2.0) if limits else 2.0
    lower = limits.get("lower", -2.0) if limits else -2.0

    fig, axs = plt.subplots(len(data), 1, figsize=(8, 4 * len(data)))
    if len(data) == 1:
        axs = [axs]

    for i, (key, values) in enumerate(data.items()):
        name_list = list(values.keys())
        val_list = list(values.values())
        label = "1 MΩ" if key == "meg" else "50 Ω"

        axs[i].set_title(f"DC Gain ({label}) - CH{channel}")
        axs[i].scatter(name_list, val_list, zorder=5)
        axs[i].plot(name_list, [upper] * len(values), "r--")
        axs[i].plot(name_list, [lower] * len(values), "r--")
        axs[i].axhline(y=0, color="gray", linestyle="-", linewidth=0.5)
        axs[i].set_ylabel("Error (%)")

    plt.tight_layout()
    plt.show()
