import math


def format_with_fixed_precision(number, precision):
    if number == 0:
        return "0." + "0" * (precision - 1)
    order = math.floor(math.log10(abs(number)))
    decimals = precision - 1 - order
    format_string = "{:." + str(max(0, decimals)) + "f}"
    formatted_number = format_string.format(number)
    parts = formatted_number.rstrip("0").split(".")
    integer_part = parts[0]
    decimal_part = parts[1] if len(parts) > 1 else ""
    if decimals > 0:
        decimal_part += "0" * (decimals - len(decimal_part))
    else:
        decimal_part = ""
    if not decimal_part:
        formatted_number = integer_part
    else:
        formatted_number = f"{integer_part}.{decimal_part}"
    return formatted_number
