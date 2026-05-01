from __future__ import annotations

import logging
from dataclasses import dataclass

from ..constants import REPO_ROOT
from .shell import subprocess_check_output

log = logging.getLogger(__name__)


@dataclass
class GitStatus:
    commit: str
    has_unstaged_changes: bool
    has_staged_uncommitted_changes: bool
    has_untracked_files: bool

    @property
    def is_clean(self) -> bool:
        return not (self.has_unstaged_changes or self.has_staged_uncommitted_changes or self.has_untracked_files)


def get_git_status() -> GitStatus | None:
    try:
        cwd = REPO_ROOT
        commit_hash = subprocess_check_output(["git", "rev-parse", "HEAD"], cwd=cwd)
        unstaged = bool(subprocess_check_output(["git", "diff", "--name-only"], cwd=cwd))
        staged = bool(subprocess_check_output(["git", "diff", "--staged", "--name-only"], cwd=cwd))
        untracked = bool(subprocess_check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=cwd))
        return GitStatus(
            commit=commit_hash, has_unstaged_changes=unstaged, has_staged_uncommitted_changes=staged, has_untracked_files=untracked
        )
    except:
        return None
