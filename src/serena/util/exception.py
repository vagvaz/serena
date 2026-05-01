import os
import sys
from enum import Enum

from serena.agent import log


def is_headless_environment() -> bool:
    """
    Detect if we're running in a headless environment where GUI operations would fail.

    Returns True if:
    - No DISPLAY variable on Linux/Unix
    - Running in SSH session
    - Running in WSL without X server
    - Running in Docker container
    """
    # Check if we're on Windows - GUI usually works there
    if sys.platform == "win32":
        return False

    # Check for DISPLAY variable (required for X11)
    if not os.environ.get("DISPLAY"):  # type: ignore
        return True

    # Check for SSH session
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_CLIENT"):
        return True

    # Check for common CI/container environments
    if os.environ.get("CI") or os.environ.get("CONTAINER") or os.path.exists("/.dockerenv"):
        return True

    # Check for WSL (only on Unix-like systems where os.uname exists)
    if hasattr(os, "uname"):
        if "microsoft" in os.uname().release.lower():
            # In WSL, even with DISPLAY set, X server might not be running
            # This is a simplified check - could be improved
            return True

    return False


def show_fatal_exception_safe(e: Exception) -> None:
    """
    Shows the given exception in the GUI log viewer on the main thread and ensures that the exception is logged or at
    least printed to stderr.
    """
    # Log the error and print it to stderr
    log.error(f"Fatal exception: {e}", exc_info=e)
    print(f"Fatal exception: {e}", file=sys.stderr)

    # Don't attempt GUI in headless environments
    if is_headless_environment():
        log.debug("Skipping GUI error display in headless environment")
        return

    # attempt to show the error in the GUI
    try:
        # NOTE: The import can fail on macOS if Tk is not available (depends on Python interpreter installation, which uv
        #   used as a base); while tkinter as such is always available, its dependencies can be unavailable on macOS.
        from serena.gui_log_viewer import show_fatal_exception

        show_fatal_exception(e)
    except Exception as gui_error:
        log.debug(f"Failed to show GUI error dialog: {gui_error}")


class ErrorCode(Enum):
    """Standardized error codes for the Serena tool system.

    Every tool error should use one of these codes so that clients can
    programmatically distinguish error types.  Errors are formatted as::

        Error [CODE]: human-readable message

    The bracketed code can be parsed by clients that support structured errors;
    the message is always readable as-is.
    """

    # Tool errors
    TOOL_PERMISSION_DENIED = "TOOL_PERMISSION_DENIED"
    """Tool is not permitted for the current session (allowlist enforcement)."""

    TOOL_NOT_ACTIVE = "TOOL_NOT_ACTIVE"
    """Tool exists but is not currently active (mode/toggle state)."""

    TOOL_EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"
    """Generic tool execution failure (exception during apply)."""

    # Project / context errors
    NO_ACTIVE_PROJECT = "NO_ACTIVE_PROJECT"
    """No active project — a project is required but none is set."""

    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    """The named project is not registered."""

    PROJECT_NOT_ACTIVE = "PROJECT_NOT_ACTIVE"
    """The project exists but is not currently active."""

    PROJECT_ACTIVATION_FAILED = "PROJECT_ACTIVATION_FAILED"
    """Failed to activate a project."""

    PROJECT_RESOLUTION_FAILED = "PROJECT_RESOLUTION_FAILED"
    """Could not resolve a project from the given path or name."""

    # Session errors
    SESSION_CONTEXT_MISSING = "SESSION_CONTEXT_MISSING"
    """An MCP connection context is required but missing."""

    SESSION_INITIALIZATION_FAILED = "SESSION_INITIALIZATION_FAILED"
    """Session initialization failed."""

    # Language server errors
    LS_NOT_READY = "LS_NOT_READY"
    """Language server is not ready to serve requests."""

    LS_CIRCUIT_OPEN = "LS_CIRCUIT_OPEN"
    """Language server circuit breaker is open — too many recent failures."""

    # Internal errors
    INTERNAL_ERROR = "INTERNAL_ERROR"
    """Unexpected internal error (bug)."""


def format_tool_error(code: ErrorCode, message: str) -> str:
    """Format a tool error as a human-readable string with embedded error code.

    The format ``Error [CODE]: message`` is both human-readable and
    machine-parseable (clients can extract the ``[CODE]`` if they want
    structured handling).
    """
    return f"Error [{code.value}]: {message}"
