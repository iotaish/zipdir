"""Interface for glob expression compilation."""

import re


class IGlobCompiler:
    """Interface for compiling glob expressions into regex patterns and structural flags."""

    def interpret(self, pattern: str) -> tuple[re.Pattern[str], bool, bool]:
        """Compile a glob pattern into (compiled_regex, is_dir_only, has_slash)."""
        raise NotImplementedError

    def compile(self, pattern: str) -> re.Pattern[str]:
        """Return only the compiled regular expression for `pattern`."""
        regex, _, _ = self.interpret(pattern)
        return regex
