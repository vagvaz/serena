"""
File buffer management extracted from SolidLanguageServer.

Provides ``FileBufferManager`` to track open file buffers and their
reference counts, separating the concern of buffer lifecycle from
LSP protocol interactions.
"""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from solidlsp.ls import LSPFileBuffer, SolidLanguageServer


class FileBufferManager:
    """
    Manages a dict of URI → ``LSPFileBuffer`` with reference counting.

    The manager handles buffer creation, lookup, and reference-count-based
    cleanup.  The actual LSP ``didOpen`` / ``didClose`` notifications are
    sent by ``LSPFileBuffer`` itself (which holds a reference to the LS).
    """

    def __init__(
        self,
        encoding: str,
        repository_root_path: str,
        language_server: "SolidLanguageServer",
    ) -> None:
        self._encoding = encoding
        self._repository_root_path = repository_root_path
        self._language_server = language_server

        self._buffers: dict[str, "LSPFileBuffer"] = {}
        """Maps URI → LSPFileBuffer for currently open files."""

    # -- public interface --------------------------------------------------

    @property
    def buffers(self) -> dict[str, "LSPFileBuffer"]:
        """Direct access to the buffer dict (for testing / legacy compat)."""
        return self._buffers

    def __contains__(self, uri: str) -> bool:
        return uri in self._buffers

    def __getitem__(self, uri: str) -> "LSPFileBuffer":
        return self._buffers[uri]

    def __len__(self) -> int:
        return len(self._buffers)

    def open(
        self,
        relative_file_path: str,
        language_id: str,
        open_in_ls: bool = True,
    ) -> "LSPFileBuffer":
        """
        Open a file buffer for *relative_file_path*.

        Returns an existing buffer (incrementing its ref count) or creates
        a new one.

        :param relative_file_path: Path relative to the repository root.
        :param language_id: The LSP language identifier.
        :param open_in_ls: Whether to send ``didOpen`` to the LS.
        :returns: The file buffer (ref count already incremented).
        """
        from solidlsp.ls import LSPFileBuffer

        abs_path = Path(self._repository_root_path, relative_file_path)
        uri = abs_path.as_uri()

        if uri in self._buffers:
            fb = self._buffers[uri]
            fb.ref_count += 1
            if open_in_ls:
                fb.ensure_open_in_ls()
            return fb

        fb = LSPFileBuffer(
            abs_path=abs_path,
            uri=uri,
            encoding=self._encoding,
            version=0,
            language_id=language_id,
            ref_count=1,
            language_server=self._language_server,
            open_in_ls=open_in_ls,
        )
        self._buffers[uri] = fb
        return fb

    def close(self, uri: str) -> None:
        """
        Release a file buffer (decrement ref count).

        When the ref count reaches zero the buffer is closed (sends
        ``didClose`` to the LS) and removed from the manager.
        """
        fb = self._buffers.get(uri)
        if fb is None:
            return
        fb.ref_count -= 1
        if fb.ref_count <= 0:
            fb.close()
            self._buffers.pop(uri, None)
