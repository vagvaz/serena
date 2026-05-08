import platform
import shlex
import subprocess


def subprocess_kwargs() -> dict:
    kwargs = {}
    if platform.system() == "Windows":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def quote_arg(arg: str) -> str:
    if platform.system() == "Windows":
        if " " not in arg:
            return arg
        return f'"{arg}"'
    return shlex.quote(arg)
