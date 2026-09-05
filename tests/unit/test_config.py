"""Unit tests for config.py — ConfigLoader, Config dataclass, and error handling.

Requirements: 10.1, 10.2, 10.3, 10.5
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from folder_organizer.config import (
    Config,
    ConfigLoader,
    ConfigMissingFieldError,
    ConfigParseError,
    ConfigValidationError,
    _DEFAULT_AI_ENDPOINT,
    _DEFAULT_AI_MODEL,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(tmp_path: Path, filename: str, content: str) -> Path:
    p = tmp_path / filename
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# ConfigLoader — valid YAML
# ---------------------------------------------------------------------------

class TestConfigLoaderValidYAML:
    def test_minimal_yaml_loads_source_dir(self, tmp_path: Path) -> None:
        """A YAML file with only source_dir produces a Config with defaults."""
        cfg_file = _write(tmp_path, "cfg.yaml", "source_dir: /my/source\n")
        cfg = ConfigLoader.load(cfg_file)
        assert cfg.source_dir == Path("/my/source")

    def test_yaml_all_fields_loaded(self, tmp_path: Path) -> None:
        """All config fields are parsed correctly from a full YAML file."""
        content = textwrap.dedent("""\
            source_dir: /src
            target_dir: /tgt
            exclude_patterns:
              - "*.tmp"
              - "*.log"
            min_confidence: 0.75
            dry_run: true
            ai_endpoint: https://custom.ai/v1
            ai_model: gpt-4
            ai_api_key: sk-test-key
            taxonomy:
              - Finance
              - Legal
        """)
        cfg_file = _write(tmp_path, "cfg.yaml", content)
        cfg = ConfigLoader.load(cfg_file)

        assert cfg.source_dir == Path("/src")
        assert cfg.target_dir == Path("/tgt")
        assert cfg.exclude_patterns == ["*.tmp", "*.log"]
        assert cfg.min_confidence == pytest.approx(0.75)
        assert cfg.dry_run is True
        assert cfg.ai_endpoint == "https://custom.ai/v1"
        assert cfg.ai_model == "gpt-4"
        assert cfg.ai_api_key == "sk-test-key"
        assert cfg.taxonomy == ["Finance", "Legal"]

    def test_yaml_defaults_applied_for_missing_optional_fields(
        self, tmp_path: Path
    ) -> None:
        """Optional fields fall back to their documented defaults."""
        cfg_file = _write(tmp_path, "cfg.yaml", "source_dir: /src\n")
        cfg = ConfigLoader.load(cfg_file)

        assert cfg.target_dir is None
        assert cfg.exclude_patterns == []
        assert cfg.min_confidence == pytest.approx(0.0)
        assert cfg.dry_run is False
        assert cfg.ai_endpoint == _DEFAULT_AI_ENDPOINT
        assert cfg.ai_model == _DEFAULT_AI_MODEL
        assert cfg.taxonomy == []

    def test_yml_extension_also_accepted(self, tmp_path: Path) -> None:
        """Files with .yml extension are parsed correctly."""
        cfg_file = _write(tmp_path, "cfg.yml", "source_dir: /src\n")
        cfg = ConfigLoader.load(cfg_file)
        assert cfg.source_dir == Path("/src")

    def test_yaml_with_zero_confidence(self, tmp_path: Path) -> None:
        """min_confidence: 0.0 is valid and loads correctly."""
        cfg_file = _write(
            tmp_path, "cfg.yaml", "source_dir: /src\nmin_confidence: 0.0\n"
        )
        cfg = ConfigLoader.load(cfg_file)
        assert cfg.min_confidence == pytest.approx(0.0)

    def test_yaml_with_max_confidence(self, tmp_path: Path) -> None:
        """min_confidence: 1.0 is valid and loads correctly."""
        cfg_file = _write(
            tmp_path, "cfg.yaml", "source_dir: /src\nmin_confidence: 1.0\n"
        )
        cfg = ConfigLoader.load(cfg_file)
        assert cfg.min_confidence == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# ConfigLoader — valid JSON
# ---------------------------------------------------------------------------

class TestConfigLoaderValidJSON:
    def test_minimal_json_loads_source_dir(self, tmp_path: Path) -> None:
        """A JSON file with only source_dir produces a Config with defaults."""
        data = {"source_dir": "/my/source"}
        cfg_file = _write(tmp_path, "cfg.json", json.dumps(data))
        cfg = ConfigLoader.load(cfg_file)
        assert cfg.source_dir == Path("/my/source")

    def test_json_all_fields_loaded(self, tmp_path: Path) -> None:
        """All config fields are parsed correctly from a full JSON file."""
        data = {
            "source_dir": "/src",
            "target_dir": "/tgt",
            "exclude_patterns": ["*.tmp", "*.bak"],
            "min_confidence": 0.5,
            "dry_run": False,
            "ai_endpoint": "https://api.example.com/v1",
            "ai_model": "gpt-3.5-turbo",
            "ai_api_key": "key-123",
            "taxonomy": ["Documents", "Images"],
        }
        cfg_file = _write(tmp_path, "cfg.json", json.dumps(data))
        cfg = ConfigLoader.load(cfg_file)

        assert cfg.source_dir == Path("/src")
        assert cfg.target_dir == Path("/tgt")
        assert cfg.exclude_patterns == ["*.tmp", "*.bak"]
        assert cfg.min_confidence == pytest.approx(0.5)
        assert cfg.dry_run is False
        assert cfg.ai_endpoint == "https://api.example.com/v1"
        assert cfg.ai_model == "gpt-3.5-turbo"
        assert cfg.ai_api_key == "key-123"
        assert cfg.taxonomy == ["Documents", "Images"]

    def test_json_defaults_applied_for_missing_optional_fields(
        self, tmp_path: Path
    ) -> None:
        """Optional fields fall back to defaults when absent from JSON."""
        cfg_file = _write(tmp_path, "cfg.json", json.dumps({"source_dir": "/src"}))
        cfg = ConfigLoader.load(cfg_file)
        assert cfg.target_dir is None
        assert cfg.exclude_patterns == []
        assert cfg.min_confidence == pytest.approx(0.0)
        assert cfg.dry_run is False
        assert cfg.ai_endpoint == _DEFAULT_AI_ENDPOINT
        assert cfg.ai_model == _DEFAULT_AI_MODEL
        assert cfg.taxonomy == []


# ---------------------------------------------------------------------------
# ConfigLoader — malformed YAML
# ---------------------------------------------------------------------------

class TestConfigLoaderMalformedYAML:
    def test_raises_config_parse_error_for_invalid_yaml(
        self, tmp_path: Path
    ) -> None:
        """Malformed YAML raises ConfigParseError."""
        bad_yaml = "source_dir: /src\n  bad_indent: [\n"
        cfg_file = _write(tmp_path, "cfg.yaml", bad_yaml)
        with pytest.raises(ConfigParseError):
            ConfigLoader.load(cfg_file)

    def test_config_parse_error_contains_file_path(self, tmp_path: Path) -> None:
        """ConfigParseError carries the path to the offending file."""
        cfg_file = _write(tmp_path, "cfg.yaml", "key: [\n  unclosed\n")
        with pytest.raises(ConfigParseError) as exc_info:
            ConfigLoader.load(cfg_file)
        assert exc_info.value.path == cfg_file

    def test_config_parse_error_contains_line_number(self, tmp_path: Path) -> None:
        """ConfigParseError carries a non-None line number for YAML parse errors."""
        # This YAML is invalid at line 2 (tab character used as indentation)
        bad_yaml = "valid_key: value\ninvalid: [\n  - unclosed\n"
        cfg_file = _write(tmp_path, "cfg.yaml", bad_yaml)
        with pytest.raises(ConfigParseError) as exc_info:
            ConfigLoader.load(cfg_file)
        # Line number should be set (not None) for YAML errors that have a mark
        assert exc_info.value.line is not None

    def test_config_parse_error_message_is_descriptive(
        self, tmp_path: Path
    ) -> None:
        """The ConfigParseError message is non-empty and mentions the file path."""
        cfg_file = _write(tmp_path, "cfg.yaml", ": bad yaml :\n  -broken")
        with pytest.raises(ConfigParseError) as exc_info:
            ConfigLoader.load(cfg_file)
        error_str = str(exc_info.value)
        assert str(cfg_file) in error_str

    def test_raises_config_parse_error_for_invalid_json(
        self, tmp_path: Path
    ) -> None:
        """Malformed JSON raises ConfigParseError."""
        cfg_file = _write(tmp_path, "cfg.json", '{"source_dir": "/src"  BROKEN}')
        with pytest.raises(ConfigParseError):
            ConfigLoader.load(cfg_file)

    def test_json_parse_error_contains_line_number(self, tmp_path: Path) -> None:
        """ConfigParseError from malformed JSON carries a line number."""
        bad_json = '{\n  "source_dir": "/src",\n  BROKEN\n}'
        cfg_file = _write(tmp_path, "cfg.json", bad_json)
        with pytest.raises(ConfigParseError) as exc_info:
            ConfigLoader.load(cfg_file)
        assert exc_info.value.line is not None

    def test_raises_config_parse_error_when_root_is_not_mapping(
        self, tmp_path: Path
    ) -> None:
        """A YAML file whose root is a list (not a mapping) raises ConfigParseError."""
        cfg_file = _write(tmp_path, "cfg.yaml", "- item1\n- item2\n")
        with pytest.raises(ConfigParseError):
            ConfigLoader.load(cfg_file)


# ---------------------------------------------------------------------------
# ConfigLoader — missing required fields
# ---------------------------------------------------------------------------

class TestConfigLoaderMissingFields:
    def test_missing_source_dir_raises_config_missing_field_error(
        self, tmp_path: Path
    ) -> None:
        """A config file without source_dir raises ConfigMissingFieldError.

        Validates: Requirements 10.5
        """
        cfg_file = _write(tmp_path, "cfg.yaml", "min_confidence: 0.3\n")
        with pytest.raises(ConfigMissingFieldError):
            ConfigLoader.load(cfg_file)

    def test_missing_source_dir_error_message_names_parameter(
        self, tmp_path: Path
    ) -> None:
        """The error message for a missing source_dir names the missing parameter."""
        cfg_file = _write(tmp_path, "cfg.yaml", "dry_run: false\n")
        with pytest.raises(ConfigMissingFieldError) as exc_info:
            ConfigLoader.load(cfg_file)
        assert "source_dir" in str(exc_info.value)


# ---------------------------------------------------------------------------
# ConfigLoader — min_confidence validation
# ---------------------------------------------------------------------------

class TestConfigLoaderConfidenceValidation:
    def test_min_confidence_above_one_raises_error(self, tmp_path: Path) -> None:
        """min_confidence > 1.0 raises ConfigValidationError.

        Validates: Requirements 10.1
        """
        cfg_file = _write(
            tmp_path, "cfg.yaml", "source_dir: /src\nmin_confidence: 1.5\n"
        )
        with pytest.raises(ConfigValidationError):
            ConfigLoader.load(cfg_file)

    def test_min_confidence_below_zero_raises_error(self, tmp_path: Path) -> None:
        """min_confidence < 0.0 raises ConfigValidationError."""
        cfg_file = _write(
            tmp_path, "cfg.yaml", "source_dir: /src\nmin_confidence: -0.1\n"
        )
        with pytest.raises(ConfigValidationError):
            ConfigLoader.load(cfg_file)

    def test_min_confidence_validation_error_message_is_descriptive(
        self, tmp_path: Path
    ) -> None:
        """The validation error message mentions min_confidence and the invalid value."""
        cfg_file = _write(
            tmp_path, "cfg.yaml", "source_dir: /src\nmin_confidence: 2.0\n"
        )
        with pytest.raises(ConfigValidationError) as exc_info:
            ConfigLoader.load(cfg_file)
        assert "min_confidence" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Config.merge_cli_overrides
# ---------------------------------------------------------------------------

class TestConfigMergeCliOverrides:
    def _base(self, tmp_path: Path) -> Config:
        return Config(
            source_dir=tmp_path / "source",
            target_dir=tmp_path / "target",
            exclude_patterns=["*.tmp"],
            min_confidence=0.4,
            dry_run=False,
            ai_endpoint="https://original.endpoint/v1",
            ai_model="gpt-3.5-turbo",
            ai_api_key=None,
            taxonomy=["Documents"],
        )

    def test_cli_source_dir_overrides_file_value(self, tmp_path: Path) -> None:
        """CLI source_dir value replaces the config-file value.

        Validates: Requirements 10.2
        """
        base = self._base(tmp_path)
        cli_source = tmp_path / "cli_source"
        merged = base.merge_cli_overrides(source_dir=cli_source)
        assert merged.source_dir == cli_source

    def test_cli_target_dir_overrides_file_value(self, tmp_path: Path) -> None:
        base = self._base(tmp_path)
        cli_target = tmp_path / "cli_target"
        merged = base.merge_cli_overrides(target_dir=cli_target)
        assert merged.target_dir == cli_target

    def test_cli_min_confidence_overrides_file_value(self, tmp_path: Path) -> None:
        base = self._base(tmp_path)
        merged = base.merge_cli_overrides(min_confidence=0.9)
        assert merged.min_confidence == pytest.approx(0.9)

    def test_cli_dry_run_overrides_file_value(self, tmp_path: Path) -> None:
        base = self._base(tmp_path)
        merged = base.merge_cli_overrides(dry_run=True)
        assert merged.dry_run is True

    def test_cli_ai_endpoint_overrides_file_value(self, tmp_path: Path) -> None:
        base = self._base(tmp_path)
        merged = base.merge_cli_overrides(ai_endpoint="https://new.endpoint/v2")
        assert merged.ai_endpoint == "https://new.endpoint/v2"

    def test_cli_ai_model_overrides_file_value(self, tmp_path: Path) -> None:
        base = self._base(tmp_path)
        merged = base.merge_cli_overrides(ai_model="gpt-4o")
        assert merged.ai_model == "gpt-4o"

    def test_none_cli_value_does_not_override(self, tmp_path: Path) -> None:
        """Passing None for a CLI flag leaves the config-file value in place.

        Validates: Requirements 10.2
        """
        base = self._base(tmp_path)
        original_endpoint = base.ai_endpoint
        merged = base.merge_cli_overrides(ai_endpoint=None)
        assert merged.ai_endpoint == original_endpoint

    def test_empty_exclude_list_does_not_override(self, tmp_path: Path) -> None:
        """An empty CLI exclude list is treated as absent (config-file value kept)."""
        base = self._base(tmp_path)
        merged = base.merge_cli_overrides(exclude_patterns=[])
        assert merged.exclude_patterns == ["*.tmp"]

    def test_non_empty_exclude_list_does_override(self, tmp_path: Path) -> None:
        """A non-empty CLI exclude list replaces the config-file value."""
        base = self._base(tmp_path)
        merged = base.merge_cli_overrides(exclude_patterns=["*.log", "*.bak"])
        assert merged.exclude_patterns == ["*.log", "*.bak"]

    def test_original_config_is_not_mutated(self, tmp_path: Path) -> None:
        """merge_cli_overrides returns a new Config without modifying the original."""
        base = self._base(tmp_path)
        original_model = base.ai_model
        base.merge_cli_overrides(ai_model="new-model")
        assert base.ai_model == original_model

    def test_no_overrides_returns_equivalent_config(self, tmp_path: Path) -> None:
        """Calling merge_cli_overrides with no arguments returns an equivalent Config."""
        base = self._base(tmp_path)
        merged = base.merge_cli_overrides()
        assert merged.source_dir == base.source_dir
        assert merged.min_confidence == base.min_confidence
        assert merged.dry_run == base.dry_run
        assert merged.ai_model == base.ai_model


# ---------------------------------------------------------------------------
# Config direct construction validation
# ---------------------------------------------------------------------------

class TestConfigDirectConstruction:
    def test_invalid_min_confidence_raises_on_construction(
        self, tmp_path: Path
    ) -> None:
        """Config() raises ConfigValidationError when min_confidence is invalid."""
        with pytest.raises(ConfigValidationError):
            Config(source_dir=tmp_path, min_confidence=2.5)

    def test_negative_min_confidence_raises_on_construction(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(ConfigValidationError):
            Config(source_dir=tmp_path, min_confidence=-0.01)

    def test_boundary_values_are_valid(self, tmp_path: Path) -> None:
        """Boundary values 0.0 and 1.0 are accepted without error."""
        cfg_low = Config(source_dir=tmp_path, min_confidence=0.0)
        cfg_high = Config(source_dir=tmp_path, min_confidence=1.0)
        assert cfg_low.min_confidence == pytest.approx(0.0)
        assert cfg_high.min_confidence == pytest.approx(1.0)
