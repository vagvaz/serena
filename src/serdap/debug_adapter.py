import logging
import os
import platform
import subprocess
import threading
from collections.abc import Callable
from queue import Queue
from typing import Any

from .adapter_config import AdapterConfig, DebugAdapterLanguage
from .dap_protocol import content_length, parse_dap_message
from .util.subprocess import quote_arg, subprocess_kwargs

log = logging.getLogger(__name__)


class DebugAdapterTerminatedException(Exception):
    def __init__(self, message: str, language: DebugAdapterLanguage, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.language = language
        self.cause = cause

    def __str__(self) -> str:
        return f"DebugAdapterTerminatedException: {self.message}" + (f"; Cause: {self.cause}" if self.cause else "")


class DebugAdapterProcess:
    @staticmethod
    def verify(adapter_config: AdapterConfig) -> str | None:
        """Check the adapter binary/module is available. Returns error msg or None."""
        import importlib
        import shutil

        cmd = adapter_config.cmd
        if not cmd:
            return "Adapter command is empty"

        binary = cmd[0]
        if binary == "python":
            module = None
            for i, part in enumerate(cmd[1:], 1):
                if part == "-m" and i + 1 < len(cmd):
                    module = cmd[i + 1]
                    break
            if module:
                try:
                    importlib.import_module(module)
                except ImportError:
                    return f"Python module '{module}' is not installed. Run: pip install {module}"
            return None

        found = shutil.which(binary)
        if found is None:
            hint = ""
            if "gdb" in binary:
                hint = " Install GDB 14+ or use: brew install gdb"
            elif "lldb-dap" in binary:
                hint = " Install LLVM 18+ or use: brew install llvm"
            return f"Adapter binary '{binary}' not found on PATH.{hint}"
        return None

    def __init__(
        self,
        adapter_config: AdapterConfig,
        language: DebugAdapterLanguage,
        on_message: Callable[[dict[str, Any]], None],
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        self.adapter_config = adapter_config
        self.language = language
        self._on_message = on_message
        self._on_error = on_error
        self.process: subprocess.Popen[bytes] | None = None
        self._is_shutting_down = False
        self._stdin_lock = threading.Lock()

    def is_running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    def start(self) -> None:
        child_proc_env = os.environ.copy()
        child_proc_env.update(self.adapter_config.env)

        cmd = self.adapter_config.cmd
        is_windows = platform.system() == "Windows"
        if not isinstance(cmd, str) and not is_windows:
            cmd = " ".join(map(quote_arg, cmd))

        log.info("Starting debug adapter process: %s", self.adapter_config.cmd)
        kwargs = subprocess_kwargs()
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=child_proc_env,
            cwd=self.adapter_config.cwd,
            shell=True,
            **kwargs,
        )

        if self.process.returncode is not None:
            stderr_data = self.process.stderr.read() if self.process.stderr else b""
            error_message = stderr_data.decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Adapter terminated immediately with code {self.process.returncode}. Error: {error_message}"
            )

        threading.Thread(
            target=self._read_stdout,
            name=f"DAP-stdout-reader:{self.language.value}",
            daemon=True,
        ).start()
        threading.Thread(
            target=self._read_stderr,
            name=f"DAP-stderr-reader:{self.language.value}",
            daemon=True,
        ).start()

    def stop(self) -> None:
        process = self.process
        self.process = None
        if process:
            self._cleanup_process(process)

    def _cleanup_process(self, process: subprocess.Popen[bytes]) -> None:
        self._safely_close_pipe(process.stdin)
        if process.returncode is None:
            self._terminate_process(process)
        self._safely_close_pipe(process.stdout)
        self._safely_close_pipe(process.stderr)

    def _safely_close_pipe(self, pipe: Any) -> None:
        if pipe:
            try:
                pipe.close()
            except Exception:
                pass

    def _terminate_process(self, process: subprocess.Popen[bytes]) -> None:
        try:
            process.terminate()
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def send_message(self, msg: dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            return
        import json
        body = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
        with self._stdin_lock:
            try:
                self.process.stdin.writelines([header, body])
                self.process.stdin.flush()
            except (BrokenPipeError, ConnectionResetError, OSError) as e:
                log.error("Failed to write to adapter stdin: %s", e)

    def send_raw(self, data: bytes) -> None:
        if not self.process or not self.process.stdin:
            return
        with self._stdin_lock:
            try:
                self.process.stdin.write(data)
                self.process.stdin.flush()
            except (BrokenPipeError, ConnectionResetError, OSError) as e:
                log.error("Failed to write to adapter stdin: %s", e)

    def _read_stdout(self) -> None:
        exception: Exception | None = None
        try:
            while self.process and self.process.stdout:
                if self.process.poll() is not None:
                    break
                line = self.process.stdout.readline()
                if not line:
                    break
                try:
                    num_bytes = content_length(line)
                except ValueError:
                    continue
                if num_bytes is None:
                    if line.strip():
                        log.warning("Unexpected line from adapter stdout (not Content-Length): %s", line)
                    continue
                while line and line.strip():
                    line = self.process.stdout.readline()
                if not line:
                    break
                body = self._read_body(num_bytes)
                if body:
                    try:
                        msg = parse_dap_message(body)
                        self._on_message(msg)
                    except Exception as e:
                        log.error("Error parsing adapter message: %s", e)
        except DebugAdapterTerminatedException as e:
            exception = e
        except (BrokenPipeError, ConnectionResetError) as e:
            exception = DebugAdapterTerminatedException(
                "Adapter process terminated while reading stdout", self.language, cause=e
            )
        except Exception as e:
            exception = DebugAdapterTerminatedException(
                "Unexpected error reading adapter stdout", self.language, cause=e
            )
        log.info("Debug adapter stdout reader thread has terminated")
        if not self._is_shutting_down and exception and self._on_error:
            self._on_error(exception)

    def _read_body(self, num_bytes: int) -> bytes:
        assert self.process and self.process.stdout
        import time
        data = b""
        while len(data) < num_bytes:
            chunk = self.process.stdout.read(num_bytes - len(data))
            if not chunk:
                if self.process.poll() is not None:
                    raise DebugAdapterTerminatedException(
                        f"Process terminated while reading response (read {len(data)} of {num_bytes} bytes)",
                        language=self.language,
                    )
                time.sleep(0.01)
                continue
            data += chunk
        return data

    def _read_stderr(self) -> None:
        try:
            while self.process and self.process.stderr:
                if self.process.poll() is not None:
                    break
                line = self.process.stderr.readline()
                if not line:
                    break
                line_str = line.decode("utf-8", errors="replace")
                log.info("[adapter stderr] %s", line_str.rstrip())
        except Exception as e:
            log.error("Error reading adapter stderr: %s", e)
