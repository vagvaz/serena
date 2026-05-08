import logging
from dataclasses import dataclass, field
from enum import Enum

log = logging.getLogger(__name__)


class DebugAdapterLanguage(str, Enum):
    PYTHON = "python"
    CPP = "cpp"

    def __str__(self) -> str:
        return self.value


@dataclass
class AdapterConfig:
    cmd: list[str]
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    adapter_name: str = ""


PYTHON_ADAPTER = AdapterConfig(
    cmd=["python", "-m", "debugpy.adapter"],
    adapter_name="debugpy",
)

CPP_ADAPTER_GDB = AdapterConfig(
    cmd=["gdb", "-i", "dap"],
    adapter_name="gdb",
)

CPP_ADAPTER_LLDB = AdapterConfig(
    cmd=["lldb-dap"],
    adapter_name="lldb-dap",
)


def get_adapter_config(language: DebugAdapterLanguage) -> AdapterConfig:
    match language:
        case DebugAdapterLanguage.PYTHON:
            return PYTHON_ADAPTER
        case DebugAdapterLanguage.CPP:
            return CPP_ADAPTER_GDB
        case _:
            raise ValueError(f"Unhandled debug adapter language: {language}")
