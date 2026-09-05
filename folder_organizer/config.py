"""Configuration dataclass and ConfigLoader.

Supports YAML and JSON config files. CLI flags always win over file values.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Optional

import yaml
import yaml.scanner

# ---------------------------------------------------------------------------
# Default constants
# ---------------------------------------------------------------------------

_DEFAULT_AI_ENDPOINT = "https://api.openai.com/v1/chat/completions"
_DEFAULT_AI_MODEL = "gpt-4o-mini"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ConfigParseError(Exception):
    """Raised when the config file cannot be parsed.

    Attributes:
        path: The config file path that failed to parse.
        line: 1-based line number where the error occurred (None if unknown).
        message: Human-readable description of the parse failure.
    """

    def __init__(self, path: Path, line: Optional[int], message: str) -> None:
        self.path = path
        self.line = line
        self.message = message
        location = f" (line {line})" if line is not None else ""
        super().__init__(f"Config parse error in {path}{location}: {message}")


class ConfigValidationError(Exception):
    """Raised when a config value is out of range or otherwise invalid."""


class ConfigMissingFieldError(Exception):
    """Raised when a required config field is absent."""


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------

@dataclass
class Config:
    """All runtime configuration for an organizer run.

    Fields
    ------
    source_dir
        Directory whose files are to be organized. Required.
    target_dir
        Root directory under which category folders are created.
        Defaults to ``source_dir`` when not specified.
    exclude_patterns
        Zero or more glob patterns; files whose relative paths match are skipped.
    min_confidence
        Minimum confidence score [0.0, 1.0] below which files are flagged for
        manual review rather than moved automatically.
    dry_run
        When *True*, no folders are created, no files are moved, and the
        metadata store is not written.
    ai_endpoint
        URL of the OpenAI-compatible chat completions endpoint.
    ai_model
        Model identifier passed to the AI API.
    ai_api_key
        API key for the AI service. Falls back to the ``OPENAI_API_KEY``
        environment variable when *None*.
    taxonomy
        List of category labels the AI is allowed to assign.
    """

    source_dir: Path
    target_dir: Optional[Path] = None
    exclude_patterns: list[str] = field(default_factory=list)
    min_confidence: float = 0.0
    dry_run: bool = False
    ai_endpoint: str = _DEFAULT_AI_ENDPOINT
    ai_model: str = _DEFAULT_AI_MODEL
    ai_api_key: Optional[str] = None
    taxonomy: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Factory / validation helpers
    # ------------------------------------------------------------------

    def __post_init__(self) -> None:
        """Validate field values after construction."""
        if not (0.0 <= self.min_confidence <= 1.0):
            raise ConfigValidationError(
                f"min_confidence must be in [0.0, 1.0], got {self.min_confidence!r}"
            )
        # Resolve ai_api_key from environment if not explicitly supplied
        if self.ai_api_key is None:
            self.ai_api_key = os.environ.get("OPENAI_API_KEY")

    # ------------------------------------------------------------------
    # CLI merge
    # ------------------------------------------------------------------

    def merge_cli_overrides(self, **kwargs: Any) -> "Config":
        """Return a new Config with CLI-provided values applied on top.

        Only keyword arguments whose values are not ``None`` (for optional
        parameters) are applied. This means callers can pass all CLI flags
        at once and unset flags (which Typer/Click typically leave as
        ``None``) are simply ignored.

        Special sentinel for ``exclude_patterns``: an empty list from the
        CLI is treated as "not provided" (i.e. the config-file value is
        kept) because Typer always initialises multi-value options to ``[]``
        even when the user supplied nothing on the command line.  Callers
        that genuinely want to clear the exclusion list should explicitly
        pass an empty list wrapped in a sentinel — or simply not pass the
        key.

        Parameters
        ----------
        **kwargs:
            Any subset of :class:`Config` field names mapped to CLI values.

        Returns
        -------
        Config
            A new :class:`Config` instance incorporating the overrides.
        """
        updates: dict[str, Any] = {}
        for key, cli_val in kwargs.items():
            if cli_val is None:
                continue
            # For list fields: a non-empty list from the CLI overrides the
            # config-file value; an empty list is treated as "not provided".
            if isinstance(cli_val, list) and len(cli_val) == 0:
                continue
            updates[key] = cli_val

        if not updates:
            return self

        # Use dataclasses.replace to produce an immutable-style copy.
        new_cfg = replace(self, **updates)
        return new_cfg


# ---------------------------------------------------------------------------
# ConfigLoader
# ---------------------------------------------------------------------------

class ConfigLoader:
    """Loads a :class:`Config` from a YAML or JSON file."""

    @staticmethod
    def load(path: Path) -> Config:
        """Parse *path* and return a :class:`Config`.

        Parameters
        ----------
        path:
            File system path to a YAML (``.yaml`` / ``.yml``) or JSON
            (``.json``) config file.

        Raises
        ------
        ConfigParseError
            If the file cannot be parsed (syntax error, wrong type at root).
        ConfigMissingFieldError
            If ``source_dir`` is absent from the file.
        ConfigValidationError
            If ``min_confidence`` is outside [0.0, 1.0].
        FileNotFoundError
            If *path* does not exist on disk.
        """
        suffix = path.suffix.lower()
        raw_text = path.read_text(encoding="utf-8")

        data: Any
        if suffix in {".yaml", ".yml"}:
            data = ConfigLoader._parse_yaml(path, raw_text)
        elif suffix == ".json":
            data = ConfigLoader._parse_json(path, raw_text)
        else:
            # Fall back to trying YAML (superset of JSON) for unknown extensions
            data = ConfigLoader._parse_yaml(path, raw_text)

        if not isinstance(data, dict):
            raise ConfigParseError(
                path, None, "Config file must be a YAML/JSON mapping at the top level"
            )

        return ConfigLoader._build_config(path, data)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_yaml(path: Path, text: str) -> Any:
        """Parse *text* as YAML, mapping parse errors to :class:`ConfigParseError`."""
        try:
            return yaml.safe_load(text)
        except yaml.YAMLError as exc:
            line: Optional[int] = None
            if hasattr(exc, "problem_mark") and exc.problem_mark is not None:
                # problem_mark.line is 0-based; convert to 1-based for humans
                line = exc.problem_mark.line + 1
            message = exc.problem if hasattr(exc, "problem") else str(exc)
            raise ConfigParseError(path, line, str(message)) from exc

    @staticmethod
    def _parse_json(path: Path, text: str) -> Any:
        """Parse *text* as JSON, mapping parse errors to :class:`ConfigParseError`."""
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigParseError(path, exc.lineno, exc.msg) from exc

    @staticmethod
    def _build_config(path: Path, data: dict[str, Any]) -> Config:
        """Construct a :class:`Config` from the parsed mapping *data*.

        Raises
        ------
        ConfigMissingFieldError
            If ``source_dir`` is not present.
        ConfigValidationError
            If ``min_confidence`` is outside [0.0, 1.0].
        """
        if "source_dir" not in data:
            raise ConfigMissingFieldError(
                "Required parameter 'source_dir' is missing from the config file"
            )

        source_dir = Path(data["source_dir"])

        target_dir_raw = data.get("target_dir")
        target_dir = Path(target_dir_raw) if target_dir_raw is not None else None

        exclude_patterns: list[str] = list(data.get("exclude_patterns", []))
        min_confidence: float = float(data.get("min_confidence", 0.0))
        dry_run: bool = bool(data.get("dry_run", False))
        ai_endpoint: str = str(data.get("ai_endpoint", _DEFAULT_AI_ENDPOINT))
        ai_model: str = str(data.get("ai_model", _DEFAULT_AI_MODEL))
        ai_api_key_raw = data.get("ai_api_key")
        ai_api_key: Optional[str] = str(ai_api_key_raw) if ai_api_key_raw is not None else None
        taxonomy: list[str] = list(data.get("taxonomy", []))

        # Config.__post_init__ will validate min_confidence
        return Config(
            source_dir=source_dir,
            target_dir=target_dir,
            exclude_patterns=exclude_patterns,
            min_confidence=min_confidence,
            dry_run=dry_run,
            ai_endpoint=ai_endpoint,
            ai_model=ai_model,
            ai_api_key=ai_api_key,
            taxonomy=taxonomy,
        )
