import fnmatch
import os
from typing import List


class IgnoreMatcher:
    """Gitignore-style matcher for bcpignore patterns."""

    def __init__(self, patterns: List[str]):
        self.patterns: List[tuple] = []
        for raw in patterns:
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            neg = raw.startswith("!")
            if neg:
                raw = raw[1:]
            dir_only = raw.endswith("/")
            if dir_only:
                raw = raw[:-1]
            self.patterns.append((raw, neg, dir_only))

    def is_ignored(self, rel_path: str, is_dir: bool = False) -> bool:
        rel_path = rel_path.replace(os.sep, "/")
        ignored = False
        for pattern, neg, dir_only in self.patterns:
            matched = False
            if dir_only:
                if is_dir and self._match_pattern(pattern, rel_path):
                    matched = True
                elif not is_dir and rel_path.startswith(pattern + "/"):
                    matched = True
                elif not is_dir and self._match_pattern(pattern, rel_path):
                    matched = True
            else:
                matched = self._match_pattern(pattern, rel_path)
            if matched:
                ignored = not neg
        return ignored

    def _match_pattern(self, pattern: str, path: str) -> bool:
        # Exact or fnmatch on full path
        if fnmatch.fnmatch(path, pattern):
            return True
        # Match basename (gitignore behavior for patterns without /)
        if "/" not in pattern and fnmatch.fnmatch(os.path.basename(path), pattern):
            return True
        # Double-star handling
        if "**" in pattern:
            return self._match_doublestar(pattern, path)
        # Prefix match for directory patterns like "dir/"
        if path.startswith(pattern + "/"):
            return True
        return False

    def _match_doublestar(self, pattern: str, path: str) -> bool:
        if pattern == "**":
            return True

        # **/suffix
        if pattern.startswith("**/"):
            suffix = pattern[3:]
            parts = path.split("/")
            for i in range(len(parts)):
                sub = "/".join(parts[i:])
                if fnmatch.fnmatch(sub, suffix):
                    return True
                if fnmatch.fnmatch(parts[i], suffix):
                    return True
            return False

        # prefix/**
        if pattern.endswith("/**"):
            prefix = pattern[:-3]
            return path == prefix or path.startswith(prefix + "/")

        # prefix/**/suffix
        if "/**/" in pattern:
            prefix, suffix = pattern.split("/**/", 1)
            if not path.startswith(prefix + "/") and path != prefix:
                return False
            rest = path[len(prefix):].lstrip("/")
            parts = rest.split("/")
            for i in range(len(parts)):
                sub = "/".join(parts[i:])
                if fnmatch.fnmatch(sub, suffix):
                    return True
                if fnmatch.fnmatch(parts[i], suffix):
                    return True
            return False

        return fnmatch.fnmatch(path, pattern)


def effective_ignores(vault_patterns: List[str], item_patterns: List[str]) -> List[str]:
    """Vault patterns first, then item patterns (item overrides vault)."""
    return list(vault_patterns) + list(item_patterns)
