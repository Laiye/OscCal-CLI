"""共享 pytest fixture 与辅助工具。

为 3 Series MDO（MDO34/MDO32）指令集与 Profile 的单元测试提供：
- 项目根路径注入 sys.path，保证可直接 import osccal
- 加载指令集 / Profile JSON 的会话级 fixture
- 用于集成测试的 FakeInstrument（模拟 pyvisa 仪器，记录写入/查询指令）
"""

import json
import sys
from pathlib import Path

import pytest

# 项目根目录注入 sys.path，确保 tests 可直接 import osccal.*
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

COMMANDS_DIR = PROJECT_ROOT / "commands"
PROFILES_DIR = PROJECT_ROOT / "profiles"
CALIBRATORS_DIR = PROJECT_ROOT / "calibrators"


# ---------------------------------------------------------------------------
# 指令集 / Profile 加载 fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def mdo3_commands() -> dict:
    """加载 3 Series MDO 指令集（tektronix_mdo3.json）。"""
    path = COMMANDS_DIR / "tektronix_mdo3.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def mdo3_commands_path() -> Path:
    return COMMANDS_DIR / "tektronix_mdo3.json"


@pytest.fixture(scope="session")
def mdo34_profile() -> dict:
    """加载 MDO34 特征配置。"""
    path = PROFILES_DIR / "tektronix_mdo34.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def mdo32_profile() -> dict:
    """加载 MDO32 特征配置。"""
    path = PROFILES_DIR / "tektronix_mdo32.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def fluke_calibrator() -> dict:
    """加载 FLUKE 9500B 校准仪配置（集成测试中用于阻抗规则查询）。"""
    path = CALIBRATORS_DIR / "fluke_9500b.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# FakeInstrument：模拟 pyvisa 仪器
# ---------------------------------------------------------------------------


class FakeInstrument:
    """模拟 pyvisa 仪器，记录所有写入/查询指令，并按预设返回查询结果。

    - write(cmd) 记录指令并返回 None（与 pyvisa write 返回写入字节数不同，
      但 comm.scpi_write 用 `inst.write(cmd) or ""`，None 会被兜底为 ""）。
    - query(cmd) 记录指令并返回预设响应；未预设时返回默认响应。
    """

    def __init__(
        self,
        query_responses: dict | None = None,
        default_response: str = ":MEASUREMENT:IMMED:VALUE 1.2340E+0",
    ):
        self.written: list[str] = []
        self.query_responses = query_responses or {}
        self.default_response = default_response

    def write(self, cmd: str):
        self.written.append(cmd)
        return None

    def query(self, cmd: str) -> str:
        self.written.append(cmd)
        return self.query_responses.get(cmd, self.default_response)

    # 便捷断言辅助
    def commands_matching(self, fragment: str) -> list[str]:
        return [c for c in self.written if fragment in c]

    def reset(self):
        self.written.clear()


@pytest.fixture
def fake_osc() -> FakeInstrument:
    """模拟被校示波器（默认返回一个合法的测量值响应）。"""
    return FakeInstrument()
