import pytest

from serdap.adapter_config import (
    DebugAdapterLanguage,
    get_adapter_config,
    PYTHON_ADAPTER,
    CPP_ADAPTER_GDB,
)


class TestDebugAdapterLanguage:
    def test_language_values(self):
        assert DebugAdapterLanguage.PYTHON.value == "python"
        assert DebugAdapterLanguage.CPP.value == "cpp"

    def test_language_str(self):
        assert str(DebugAdapterLanguage.PYTHON) == "python"
        assert str(DebugAdapterLanguage.CPP) == "cpp"

    def test_get_adapter_config_python(self):
        config = get_adapter_config(DebugAdapterLanguage.PYTHON)
        assert config is PYTHON_ADAPTER
        assert "debugpy" in config.cmd[-1]
        assert config.adapter_name == "debugpy"

    def test_get_adapter_config_cpp(self):
        config = get_adapter_config(DebugAdapterLanguage.CPP)
        assert config is CPP_ADAPTER_GDB
        assert "gdb" in config.cmd[0]
        assert config.adapter_name == "gdb"

    def test_get_adapter_config_invalid(self):
        with pytest.raises(ValueError, match="Unhandled debug adapter language"):
            get_adapter_config("invalid")  # type: ignore[arg-type]

    def test_from_string(self):
        assert DebugAdapterLanguage("python") == DebugAdapterLanguage.PYTHON
        assert DebugAdapterLanguage("cpp") == DebugAdapterLanguage.CPP

    def test_from_string_invalid(self):
        with pytest.raises(ValueError):
            DebugAdapterLanguage("rust")
