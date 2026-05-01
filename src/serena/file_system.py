"""
File system operations for a Serena project.

Provides ProjectFileSystem — extracting file I/O, ignore pattern matching,
source file discovery, and path validation from the Project class.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import pathspec
from serena.util.logging import LogTime

from serena.util.file_system import GitignoreParser, match_path
from solidlsp.ls_utils import FileUtils

if TYPE_CHECKING:
    from serena.config.serena_config import ProjectConfig, SerenaConfig

log = logging.getLogger(__name__)


class ProjectFileSystem:
    """
    File system operations for a project: reading files, checking ignore
    patterns, discovering source files, and searching file content.

    This is the seam between Project (identity/config) and the filesystem.
    It can be tested with a temp directory without a full Project instance.
    """

    def __init__(
        self,
        project_root: str,
        project_config: ProjectConfig,
        serena_config: SerenaConfig,
    ) -> None:
        """
        :param project_root: absolute path to the project root directory
        :param project_config: the project's configuration (languages, ignored paths, encoding)
        :param serena_config: the global Serena configuration (global ignored paths)
        """
        self.project_root = project_root
        self.project_config = project_config
        self.serena_config = serena_config

        # prepare ignore spec asynchronously
        self.__ignored_patterns: list[str] | None = None
        self.__ignore_spec: pathspec.PathSpec | None = None
        self._ignore_spec_available = threading.Event()
        threading.Thread(
            name=f"gather-ignorespec[{self.project_config.project_name}]",
            target=self._gather_ignorespec,
            daemon=True,
        ).start()

    # ── Ignore spec ─────────────────────────────────────────────────

    def _gather_ignorespec(self) -> None:
        """Asynchronously gather ignore patterns from config + .gitignore files."""
        with LogTime(f"Gathering ignore spec for project {self.project_config.project_name}", logger=log):
            try:
                global_ignored_paths = self.serena_config.ignored_paths
                ignored_patterns = list(global_ignored_paths) + list(self.project_config.ignored_paths)
                if len(global_ignored_paths) > 0:
                    log.info(f"Using {len(global_ignored_paths)} ignored paths from the global configuration.")
                    log.debug(f"Global ignored paths: {list(global_ignored_paths)}")
                if len(self.project_config.ignored_paths) > 0:
                    log.info(f"Using {len(self.project_config.ignored_paths)} ignored paths from the project configuration.")
                    log.debug(f"Project ignored paths: {self.project_config.ignored_paths}")
                log.debug(f"Combined ignored patterns: {ignored_patterns}")
                if self.project_config.ignore_all_files_in_gitignore:
                    gitignore_parser = GitignoreParser(self.project_root)
                    for spec in gitignore_parser.get_ignore_specs():
                        log.debug(f"Adding {len(spec.patterns)} patterns from {spec.file_path} to the ignored paths.")
                        ignored_patterns.extend(spec.patterns)
                self.__ignored_patterns = ignored_patterns

                processed_patterns = []
                for pattern in ignored_patterns:
                    pattern = pattern.replace(os.path.sep, "/")
                    processed_patterns.append(pattern)
                log.debug(f"Processing {len(processed_patterns)} ignored paths")
                self.__ignore_spec = pathspec.PathSpec.from_lines(
                    pathspec.patterns.GitWildMatchPattern, processed_patterns
                )
            except Exception as e:
                log.error(
                    f"Error while gathering ignore spec for project {self.project_config.project_name}: {e}",
                    exc_info=e,
                )

        self._ignore_spec_available.set()

    @property
    def _ignore_spec(self) -> pathspec.PathSpec:
        if not self._ignore_spec_available.is_set():
            log.info("Waiting for ignore spec to become available ...")
            self._ignore_spec_available.wait()
            if self.__ignore_spec is not None:
                log.info("Ignore spec is now available for project; proceeding")
        if self.__ignore_spec is None:
            raise ValueError(
                "The ignore spec could not be computed; please check the log for errors "
                "and report here: https://github.com/oraios/serena/issues"
            )
        return self.__ignore_spec

    @property
    def _ignored_patterns(self) -> list[str]:
        if not self._ignore_spec_available.is_set():
            log.info("Waiting for ignored patterns to become available ...")
            self._ignore_spec_available.wait()
            if self.__ignored_patterns is not None:
                log.info("Ignored patterns are now available for project; proceeding")
        if self.__ignored_patterns is None:
            raise ValueError(
                "The ignored patterns could not be computed; please check the log for errors "
                "and report here: https://github.com/oraios/serena/issues"
            )
        return self.__ignored_patterns

    # ── File I/O ────────────────────────────────────────────────────

    def read_file(self, relative_path: str) -> str:
        """
        Read a file relative to the project root.

        :param relative_path: the path to the file relative to the project root
        :return: the content of the file
        """
        abs_path = Path(self.project_root) / relative_path
        return FileUtils.read_file(str(abs_path), self.project_config.encoding)

    # ── Path validation ─────────────────────────────────────────────

    def is_path_in_project(self, path: str | Path) -> bool:
        """
        Check if the given (absolute or relative) path is inside the project directory.

        Note: This is intended to catch cases where ".." segments would lead outside
        of the project directory, but we intentionally allow symlinks.
        """
        if not os.path.isabs(path):
            path = os.path.join(self.project_root, path)
        path = os.path.normpath(path)
        try:
            return os.path.commonpath([self.project_root, path]) == self.project_root
        except ValueError:
            return False

    def relative_path_exists(self, relative_path: str) -> bool:
        """Check if the given relative path exists in the project directory."""
        abs_path = Path(self.project_root) / relative_path
        return abs_path.exists()

    def validate_relative_path(self, relative_path: str, require_not_ignored: bool = False) -> None:
        """
        Validate that the given relative path is safe to read or edit.

        :param relative_path: path relative to the project root
        :param require_not_ignored: if True, the path must not be ignored
        :raises ValueError: if path is outside project or (optionally) ignored
        :raises FileNotFoundError: if path does not exist
        """
        if not self.is_path_in_project(relative_path):
            raise ValueError(
                f"{relative_path=} points to path outside of the repository root; "
                "cannot access for safety reasons"
            )
        if require_not_ignored:
            if self.is_ignored_path(relative_path):
                raise ValueError(f"Path {relative_path} is ignored; cannot access for safety reasons")

    # ── Ignore checking ─────────────────────────────────────────────

    def is_ignored_path(self, path: str | Path, ignore_non_source_files: bool = False) -> bool:
        """
        Check whether the given path is ignored.

        :param path: absolute or relative path
        :param ignore_non_source_files: whether to also ignore non-source files
        """
        path = Path(path)
        if path.is_absolute():
            try:
                relative_path = path.relative_to(self.project_root)
            except ValueError:
                log.warning(
                    f"Path {path} is not relative to the project root {self.project_root} "
                    "and was therefore ignored"
                )
                return True
        else:
            relative_path = path
        return self._is_ignored_relative_path(str(relative_path), ignore_non_source_files=ignore_non_source_files)

    def _is_ignored_relative_path(
        self, relative_path: str | Path, ignore_non_source_files: bool = True
    ) -> bool:
        """
        Determine whether an existing path should be ignored.

        :raises FileNotFoundError: if the path does not exist
        """
        if str(relative_path) in [".", ""]:
            return False

        abs_path = os.path.join(self.project_root, relative_path)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(
                f"File {abs_path} not found, the ignore check cannot be performed"
            )

        is_file = os.path.isfile(abs_path)
        if is_file and ignore_non_source_files:
            is_file_in_supported_language = False
            for language in self.project_config.languages:
                fn_matcher = language.get_source_fn_matcher()
                if fn_matcher.is_relevant_filename(abs_path):
                    is_file_in_supported_language = True
                    break
            if not is_file_in_supported_language:
                return True

        rel_path = Path(relative_path)
        if len(rel_path.parts) > 0 and ".git" in rel_path.parts:
            return True

        return match_path(str(relative_path), self._ignore_spec, root_path=self.project_root)

    # ── Source file discovery ───────────────────────────────────────

    def gather_source_files(self, relative_path: str = "") -> list[str]:
        """Retrieve relative paths of all source files, optionally limited to the given path.

        :param relative_path: if provided, restrict search to this path
        """
        rel_file_paths = []
        start_path = os.path.join(self.project_root, relative_path)
        if not os.path.exists(start_path):
            raise FileNotFoundError(f"Relative path {start_path} not found.")
        if os.path.isfile(start_path):
            return [relative_path]
        for root, dirs, files in os.walk(start_path, followlinks=True):
            dirs[:] = [d for d in dirs if not self.is_ignored_path(os.path.join(root, d))]
            for file in files:
                abs_file_path = os.path.join(root, file)
                try:
                    if not self.is_ignored_path(abs_file_path, ignore_non_source_files=True):
                        try:
                            rel_file_path = os.path.relpath(abs_file_path, start=self.project_root)
                        except Exception:
                            log.warning(
                                "Ignoring path '%s' because it appears to be outside of the project root (%s)",
                                abs_file_path,
                                self.project_root,
                            )
                            continue
                        rel_file_paths.append(rel_file_path)
                except FileNotFoundError:
                    log.warning(
                        f"File {abs_file_path} not found (possibly due it being a symlink), "
                        "skipping it in request_parsed_files",
                    )
        return rel_file_paths

    # ── Content search ──────────────────────────────────────────────

    def search_source_files_for_pattern(
        self,
        pattern: str,
        relative_path: str = "",
        context_lines_before: int = 0,
        context_lines_after: int = 0,
        paths_include_glob: str | None = None,
        paths_exclude_glob: str | None = None,
    ) -> list["MatchedConsecutiveLines"]:
        """Search for a pattern across all (non-ignored) source files.

        :param pattern: regular expression pattern to search for
        :param relative_path: restrict search to this path
        :param context_lines_before: lines of context before each match
        :param context_lines_after: lines of context after each match
        :param paths_include_glob: glob to filter files to include
        :param paths_exclude_glob: glob to filter files to exclude
        """
        from serena.util.text_utils import MatchedConsecutiveLines, search_files
        relative_file_paths = self.gather_source_files(relative_path=relative_path)
        return search_files(
            relative_file_paths,
            pattern,
            root_path=self.project_root,
            file_reader=self.read_file,
            context_lines_before=context_lines_before,
            context_lines_after=context_lines_after,
            paths_include_glob=paths_include_glob,
            paths_exclude_glob=paths_exclude_glob,
        )

    def retrieve_content_around_line(
        self,
        relative_file_path: str,
        line: int,
        context_lines_before: int = 0,
        context_lines_after: int = 0,
    ) -> "MatchedConsecutiveLines":
        """Retrieve file content around a given line number.

        :param relative_file_path: path relative to project root
        :param line: 0-based line number
        :param context_lines_before: lines before the target line
        :param context_lines_after: lines after the target line
        """
        from serena.util.text_utils import MatchedConsecutiveLines
        file_contents = self.read_file(relative_file_path)
        return MatchedConsecutiveLines.from_file_contents(
            file_contents,
            line=line,
            context_lines_before=context_lines_before,
            context_lines_after=context_lines_after,
            source_file_path=relative_file_path,
        )
