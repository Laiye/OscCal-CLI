"""format_with_fixed_precision 回归测试。

重点覆盖 P0 修复：当有效数字恰好没有小数位时，整数尾零曾被 `.rstrip("0")`
误删（如 1000 -> "1"、10 -> "1"），会污染显示值并影响以该结果反算的误差。
"""

import pytest

from osccal.core.utils import format_with_fixed_precision


class TestIntegerTrailingZeros:
    @pytest.mark.parametrize(
        "number,precision,expected",
        [
            (1000, 3, "1000"),
            (100, 3, "100"),
            (2500, 3, "2500"),
            (10, 2, "10"),
            (20, 2, "20"),
            (100, 2, "100"),
            (-1000, 3, "-1000"),
        ],
    )
    def test_no_zero_stripping_on_integers(self, number, precision, expected):
        assert format_with_fixed_precision(number, precision) == expected


class TestDecimalsPreserved:
    @pytest.mark.parametrize(
        "number,precision,expected",
        [
            (10, 4, "10.00"),
            (500, 4, "500.0"),
            (1.0, 3, "1.00"),
            (1.234, 3, "1.23"),
            (5.5, 2, "5.5"),
            (0.001, 3, "0.00100"),
            (8e-8, 4, "0.00000008000"),
        ],
    )
    def test_decimal_part_formatting(self, number, precision, expected):
        assert format_with_fixed_precision(number, precision) == expected


def test_zero_value():
    assert format_with_fixed_precision(0, 3) == "0.00"
    assert format_with_fixed_precision(0.0, 2) == "0.0"


def test_roundtrip_float_used_by_calibration_math():
    """校准器用 float(format(...)) 反算误差，结果必须能还原原数量级。"""
    assert float(format_with_fixed_precision(1000, 3)) == pytest.approx(1000.0)
    assert float(format_with_fixed_precision(100, 3)) == pytest.approx(100.0)
