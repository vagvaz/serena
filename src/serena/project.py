import logging
import os
import re
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Optional

from serena.util.string_utils import TextBuilder, ToStringMixin

from serena.config.serena_config import (
    ProjectConfig,
    SerenaConfig,
    SerenaPaths,
)
from serena.constants import SERENA_FILE_ENCODING
from serena.file_system import ProjectFileSystem
from serena.ls_manager import LanguageServerFactory, LanguageServerManager
from serena.util.text_utils import ContentReplacer, MatchedConsecutiveLines
from solidlsp import SolidLanguageServer
from solidlsp.ls_config import Language

if TYPE_CHECKING:
    from serena.agent import SerenaAgent

log = logging.getLogger(__name__)


class MemoriesManager:
    GLOBAL_TOPIC = "global"
    _global_memory_dir = SerenaPaths().global_memories_path

    def __init__(
        self,
        serena_data_folder: str | Path | None,
        read_only_memory_patterns: Sequence[str] = (),
        ignored_memory_patterns: Sequence[str] = (),
    ):
        """
        :param serena_data_folder: the absolute path to the project's .serena data folder
        :param read_only_memory_patterns: whether to allow writing global memories in tool execution contexts
        :param ignored_memory_patterns: regex patterns for memories to completely exclude from listing, reading, and writing.
            Matching memories will not appear in list_memories or activate_project output and cannot be accessed
            via read_memory or write_memory. Use read_file on the raw path to access ignored memory files.
        """
        self._project_memory_dir: Path | None = None
        if serena_data_folder is not None:
            self._project_memory_dir = Path(serena_data_folder) / "memories"
            self._project_memory_dir.mkdir(parents=True, exist_ok=True)
        self._encoding = SERENA_FILE_ENCODING
        self._read_only_memory_patterns = [re.compile(pattern) for pattern in set(read_only_memory_patterns)]
        self._ignored_memory_patterns = [re.compile(pattern) for pattern in set(ignored_memory_patterns)]

    def _is_read_only_memory(self, name: str) -> bool:
        for pattern in self._read_only_memory_patterns:
            if pattern.fullmatch(name):
                return True
        return False

    def _is_ignored_memory(self, name: str) -> bool:
        for pattern in self._ignored_memory_patterns:
            if pattern.fullmatch(name):
                return True
        return False

    def _check_not_ignored(self, name: str) -> None:
        if self._is_ignored_memory(name):
            raise ValueError(
                f"Memory '{name}' matches an ignored_memory_patterns pattern and cannot be accessed. "
                f"Use the read_file tool on the raw file path instead."
            )

    def _is_global(self, name: str) -> bool:
        return name == self.GLOBAL_TOPIC or name.startswith(self.GLOBAL_TOPIC + "/")

    def get_memory_file_path(self, name: str) -> Path:
        # Strip .md extension if present
        name = name.replace(".md", "").replace(os.sep, "/")
        parts = name.split("/")
        if ".." in parts:
            raise ValueError(f"Memory name cannot contain '..' segments for security reasons. Got: {name}")

        if self._is_global(name):
            if name == self.GLOBAL_TOPIC:
                raise ValueError(
                    f'Bare "{self.GLOBAL_TOPIC}" is not a valid memory name. Use "{self.GLOBAL_TOPIC}/<name>" to address a global memory.'
                )
            # Strip "global/" prefix and resolve against global dir
            sub_name = name[len(self.GLOBAL_TOPIC) + 1 :]
            parts = sub_name.split("/")
            filename = f"{parts[-1]}.md"
            if len(parts) > 1:
                subdir = self._global_memory_dir / "/".join(parts[:-1])
                subdir.mkdir(parents=True, exist_ok=True)
                return subdir / filename
            return self._global_memory_dir / filename

        # Project-local memory
        assert self._project_memory_dir is not None, "Project dir was not passed at initialization"

        filename = f"{parts[-1]}.md"

        if len(parts) > 1:
            # Create subdirectory path
            subdir = self._project_memory_dir / "/".join(parts[:-1])
            subdir.mkdir(parents=True, exist_ok=True)
            return subdir / filename

        return self._project_memory_dir / filename

    def _check_write_access(self, name: str, is_tool_context: bool) -> None:
        # in tool context, memories can be read-only
        if is_tool_context and self._is_read_only_memory(name):
            raise PermissionError(f"Attempted to write to read_only memory: '{name}')")

    def load_memory(self, name: str) -> str:
        self._check_not_ignored(name)
        memory_file_path = self.get_memory_file_path(name)
        if not memory_file_path.exists():
            return f"Memory file {name} not found, consider creating it with the `write_memory` tool if you need it."
        with open(memory_file_path, encoding=self._encoding) as f:
            return f.read()

    def save_memory(self, name: str, content: str, is_tool_context: bool) -> str:
        self._check_not_ignored(name)
        self._check_write_access(name, is_tool_context)
        memory_file_path = self.get_memory_file_path(name)
        with open(memory_file_path, "w", encoding=self._encoding) as f:
            f.write(content)
        return f"Memory {name} written."

    class MemoriesList:
        def __init__(self) -> None:
            self.memories: list[str] = []
            self.read_only_memories: list[str] = []

        def __len__(self) -> int:
            return len(self.memories) + len(self.read_only_memories)

        def add(self, memory_name: str, is_read_only: bool) -> None:
            if is_read_only:
                self.read_only_memories.append(memory_name)
            else:
                self.memories.append(memory_name)

        def extend(self, other: "MemoriesManager.MemoriesList") -> None:
            self.memories.extend(other.memories)
            self.read_only_memories.extend(other.read_only_memories)

        def to_dict(self) -> dict[str, list[str]]:
            result = {}
            if self.memories:
                result["memories"] = sorted(self.memories)
            if self.read_only_memories:
                result["read_only_memories"] = sorted(self.read_only_memories)
            return result

        def get_full_list(self) -> list[str]:
            return sorted(self.memories + self.read_only_memories)

    def _list_memories(self, search_dir: Path, base_dir: Path, prefix: str = "") -> MemoriesList:
        result = self.MemoriesList()
        if not search_dir.exists():
            return result
        for md_file in search_dir.rglob("*.md"):
            rel = str(md_file.relative_to(base_dir).with_suffix("")).replace(os.sep, "/")
            memory_name = prefix + rel
            if self._is_ignored_memory(memory_name):
                continue
            result.add(memory_name, is_read_only=self._is_read_only_memory(memory_name))
        return result

    def list_global_memories(self, subtopic: str = "") -> MemoriesList:
        dir_path = self._global_memory_dir
        if subtopic:
            dir_path = dir_path / subtopic.replace("/", os.sep)
        return self._list_memories(dir_path, self._global_memory_dir, self.GLOBAL_TOPIC + "/")

    def list_project_memories(self, topic: str = "") -> MemoriesList:
        assert self._project_memory_dir is not None, "Project dir was not passed at initialization"
        dir_path = self._project_memory_dir
        if topic:
            dir_path = dir_path / topic.replace("/", os.sep)
        return self._list_memories(dir_path, self._project_memory_dir)

    def list_memories(self, topic: str = "") -> MemoriesList:
        """
        Lists all memories, optionally filtered by topic.
        If the topic is omitted, both global and project-specific memories are returned.
        """
        memories: MemoriesManager.MemoriesList

        if topic:
            if self._is_global(topic):
                topic_parts = topic.split("/")
                subtopic = "/".join(topic_parts[1:])
                memories = self.list_global_memories(subtopic=subtopic)
            else:
                memories = self.list_project_memories(topic=topic)
        else:
            memories = self.list_project_memories()
            memories.extend(self.list_global_memories())

        return memories

    def delete_memory(self, name: str, is_tool_context: bool) -> str:
        self._check_not_ignored(name)
        self._check_write_access(name, is_tool_context)
        memory_file_path = self.get_memory_file_path(name)
        if not memory_file_path.exists():
            return f"Memory {name} not found."
        memory_file_path.unlink()
        return f"Memory {name} deleted."

    def move_memory(self, old_name: str, new_name: str, is_tool_context: bool) -> str:
        """
        Rename or move a memory file.
        Moving between global and project scope (e.g. "global/foo" -> "bar") is supported.
        """
        self._check_not_ignored(old_name)
        self._check_not_ignored(new_name)
        self._check_write_access(new_name, is_tool_context)

        old_path = self.get_memory_file_path(old_name)
        new_path = self.get_memory_file_path(new_name)

        if not old_path.exists():
            raise FileNotFoundError(f"Memory {old_name} not found.")
        if new_path.exists():
            raise FileExistsError(f"Memory {new_name} already exists.")

        new_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(old_path, new_path)

        return f"Memory renamed from {old_name} to {new_name}."

    def edit_memory(
        self, name: str, needle: str, repl: str, mode: Literal["literal", "regex"], allow_multiple_occurrences: bool, is_tool_context: bool
    ) -> str:
        """
        Edit a memory by replacing content matching a pattern.

        :param name: the memory name
        :param needle: the string or regex to search for
        :param repl: the replacement string
        :param mode: "literal" or "regex"
        :param allow_multiple_occurrences:
        """
        self._check_not_ignored(name)
        self._check_write_access(name, is_tool_context)
        memory_file_path = self.get_memory_file_path(name)
        if not memory_file_path.exists():
            raise FileNotFoundError(f"Memory {name} not found.")
        with open(memory_file_path, encoding=self._encoding) as f:
            original_content = f.read()
        replacer = ContentReplacer(mode=mode, allow_multiple_occurrences=allow_multiple_occurrences)
        updated_content = replacer.replace(original_content, needle, repl)
        with open(memory_file_path, "w", encoding=self._encoding) as f:
            f.write(updated_content)
        return f"Memory {name} edited successfully."


class Project(ToStringMixin):
    def __init__(
        self,
        *,
        project_root: str,
        project_config: ProjectConfig,
        serena_config: SerenaConfig,
        is_newly_created: bool = False,
    ):
        assert serena_config is not None
        self.project_root = project_root
        self.project_config = project_config
        self.serena_config = serena_config
        self._serena_data_folder = serena_config.get_project_serena_folder(self.project_root)
        log.info("Serena project data folder: %s", self._serena_data_folder)

        read_only_memory_patterns = serena_config.read_only_memory_patterns + project_config.read_only_memory_patterns
        ignored_memory_patterns = serena_config.ignored_memory_patterns + project_config.ignored_memory_patterns
        self.memories_manager = MemoriesManager(
            self._serena_data_folder,
            read_only_memory_patterns=read_only_memory_patterns,
            ignored_memory_patterns=ignored_memory_patterns,
        )

        # resolve line ending (project -> global)
        self.line_ending = project_config.line_ending or serena_config.line_ending

        self.language_server_manager: LanguageServerManager | None = None
        self._language_server_manager_init_error: Exception | None = None
        self.is_newly_created = is_newly_created
        self._agent: Optional["SerenaAgent"] = None

        # create the file system adapter
        self._filesystem = ProjectFileSystem(project_root, self.project_config, self.serena_config)

        # create .gitignore file in the project's Serena data folder if not yet present
        serena_data_gitignore_path = os.path.join(self._serena_data_folder, ".gitignore")
        if not os.path.exists(serena_data_gitignore_path):
            os.makedirs(os.path.dirname(serena_data_gitignore_path), exist_ok=True)
            log.info(f"Creating .gitignore file in {serena_data_gitignore_path}")
            with open(serena_data_gitignore_path, "w", encoding="utf-8") as f:
                f.write(f"/{SolidLanguageServer.CACHE_FOLDER_NAME}\n")
                f.write(f"/{ProjectConfig.SERENA_LOCAL_PROJECT_FILE}\n")

    @property
    def filesystem(self) -> ProjectFileSystem:
        """Access the project file system adapter."""
        return self._filesystem

    def _tostring_includes(self) -> list[str]:
        return []

    def _tostring_additional_entries(self) -> dict[str, Any]:
        return {"root": self.project_root, "name": self.project_name}

    def set_agent(self, agent: "SerenaAgent") -> None:
        self._agent = agent

    @property
    def project_name(self) -> str:
        return self.project_config.project_name

    @classmethod
    def load(
        cls,
        project_root: str | Path,
        serena_config: "SerenaConfig",
        autogenerate: bool = True,
    ) -> "Project":
        assert serena_config is not None
        project_root = Path(project_root).resolve()
        if not project_root.exists():
            raise FileNotFoundError(f"Project root not found: {project_root}")
        project_config = ProjectConfig.load(project_root, serena_config=serena_config, autogenerate=autogenerate)
        return Project(project_root=str(project_root), project_config=project_config, serena_config=serena_config)

    def save_config(self) -> None:
        """
        Saves the current project configuration to disk.
        """
        self.project_config.save(self.path_to_project_yml())

    def path_to_serena_data_folder(self) -> str:
        return self._serena_data_folder

    @property
    def serena_folder(self) -> str:
        """Alias for path_to_serena_data_folder() for convenience."""
        return self._serena_data_folder

    def path_to_project_yml(self) -> str:
        return self.serena_config.get_project_yml_location(self.project_root)

    def read_file(self, relative_path: str) -> str:
        """Read a file relative to the project root. Delegates to ProjectFileSystem."""
        return self._filesystem.read_file(relative_path)

    def is_ignored_path(self, path: str | Path, ignore_non_source_files: bool = False) -> bool:
        """Check whether the given path is ignored. Delegates to ProjectFileSystem."""
        return self._filesystem.is_ignored_path(path, ignore_non_source_files=ignore_non_source_files)

    def is_path_in_project(self, path: str | Path) -> bool:
        """Check if the given path is inside the project directory. Delegates to ProjectFileSystem."""
        return self._filesystem.is_path_in_project(path)

    def relative_path_exists(self, relative_path: str) -> bool:
        """Check if the given relative path exists. Delegates to ProjectFileSystem."""
        return self._filesystem.relative_path_exists(relative_path)

    def validate_relative_path(self, relative_path: str, require_not_ignored: bool = False) -> None:
        """Validate that the given relative path is safe. Delegates to ProjectFileSystem."""
        self._filesystem.validate_relative_path(relative_path, require_not_ignored=require_not_ignored)

    def gather_source_files(self, relative_path: str = "") -> list[str]:
        """Retrieve relative paths of all source files. Delegates to ProjectFileSystem."""
        return self._filesystem.gather_source_files(relative_path=relative_path)

    def search_source_files_for_pattern(
        self,
        pattern: str,
        relative_path: str = "",
        context_lines_before: int = 0,
        context_lines_after: int = 0,
        paths_include_glob: str | None = None,
        paths_exclude_glob: str | None = None,
    ) -> list[MatchedConsecutiveLines]:
        """Search for a pattern across source files. Delegates to ProjectFileSystem."""
        return self._filesystem.search_source_files_for_pattern(
            pattern,
            relative_path=relative_path,
            context_lines_before=context_lines_before,
            context_lines_after=context_lines_after,
            paths_include_glob=paths_include_glob,
            paths_exclude_glob=paths_exclude_glob,
        )

    def retrieve_content_around_line(
        self, relative_file_path: str, line: int, context_lines_before: int = 0, context_lines_after: int = 0
    ) -> MatchedConsecutiveLines:
        """Retrieve content around a line. Delegates to ProjectFileSystem."""
        return self._filesystem.retrieve_content_around_line(
            relative_file_path, line=line,
            context_lines_before=context_lines_before,
            context_lines_after=context_lines_after,
        )

    def create_language_server_manager(self) -> LanguageServerManager:
        """
        Creates the language server manager for the project, starting one language server per configured programming language.

        :return: the language server manager, which is also stored in the project instance
        """
        try:
            # determine timeout to use for LS calls
            tool_timeout = self.serena_config.tool_timeout
            if tool_timeout is None or tool_timeout < 0:
                ls_timeout = None
            else:
                if tool_timeout < 10:
                    raise ValueError(f"Tool timeout must be at least 10 seconds, but is {tool_timeout} seconds")
                ls_timeout = tool_timeout - 5  # the LS timeout is for a single call, it should be smaller than the tool timeout

            # if there is an existing instance, stop its language servers first
            if self.language_server_manager is not None:
                log.info("Stopping existing language server manager ...")
                self.language_server_manager.stop_all()
                self.language_server_manager = None

            log.info(f"Creating language server manager for {self.project_root}")
            self._language_server_manager_init_error = None
            ls_specific_settings = {**self.serena_config.ls_specific_settings, **self.project_config.ls_specific_settings}
            factory = LanguageServerFactory(
                project_root=self.project_root,
                project_data_path=self._serena_data_folder,
                encoding=self.project_config.encoding,
                ignored_patterns=self._filesystem._ignored_patterns,
                ls_timeout=ls_timeout,
                ls_specific_settings=ls_specific_settings,
                trace_lsp_communication=self.serena_config.trace_lsp_communication,
            )
            self.language_server_manager = LanguageServerManager.from_languages(self.project_config.languages, factory)
            return self.language_server_manager
        except Exception as e:
            self._language_server_manager_init_error = e
            raise

    def get_language_server_manager_or_raise(self) -> LanguageServerManager:
        if self.language_server_manager is None:
            msg = TextBuilder("The language server manager is not initialized, indicating a problem during project initialisation.")
            if self._language_server_manager_init_error is not None:
                msg.with_text(str(self._language_server_manager_init_error))
            if self._agent is not None:
                msg.with_text("For details, please check the logs. " + self._agent.get_log_inspection_instructions())
            msg.with_text(
                "IMPORTANT: Stop, do not attempt workarounds. Inform the user and wait for further instructions before you continue!"
            )
            raise Exception(msg.build())
        return self.language_server_manager

    def add_language(self, language: Language) -> None:
        """
        Adds a new programming language to the project configuration, starting the corresponding
        language server instance if the LS manager is active.
        The project configuration is saved to disk after adding the language.

        :param language: the programming language to add
        """
        if language in self.project_config.languages:
            log.info(f"Language {language.value} is already present in the project configuration.")
            return

        # start the language server (if the LS manager is active)
        if self.language_server_manager is None:
            log.info("Language server manager is not active; skipping language server startup for the new language.")
        else:
            log.info("Adding and starting the language server for new language %s ...", language.value)
            self.language_server_manager.add_language_server(language)

        # update the project configuration
        self.project_config.languages.append(language)
        self.save_config()

    def remove_language(self, language: Language) -> None:
        """
        Removes a programming language from the project configuration, stopping the corresponding
        language server instance if the LS manager is active.
        The project configuration is saved to disk after removing the language.

        :param language: the programming language to remove
        """
        if language not in self.project_config.languages:
            log.info(f"Language {language.value} is not present in the project configuration.")
            return
        # update the project configuration
        self.project_config.languages.remove(language)
        self.save_config()

        # stop the language server (if the LS manager is active)
        if self.language_server_manager is None:
            log.info("Language server manager is not active; skipping language server shutdown for the removed language.")
        else:
            log.info("Removing and stopping the language server for language %s ...", language.value)
            self.language_server_manager.remove_language_server(language)

    def shutdown(self, timeout: float = 2.0) -> None:
        if self.language_server_manager is not None:
            self.language_server_manager.stop_all(save_cache=True, timeout=timeout)
            self.language_server_manager = None
