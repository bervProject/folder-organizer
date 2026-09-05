# Feature: local-file-organizer, Property 19: CLI flags override config file values

"""Property-based tests verifying that CLI flag values always take precedence
over the values loaded from a config file.

Validates: Requirements 10.2
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from folder_organizer.config import Config, _DEFAULT_AI_ENDPOINT, _DEFAULT_AI_MODEL


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Paths are generated as relative strings and then wrapped in Path so they
# survive dataclass construction without touching the real file system.
_path_st = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), min_codepoint=1),
    min_size=1,
    max_size=30,
).map(lambda s: Path(s))

_optional_path_st = st.one_of(st.none(), _path_st)

_exclude_st = st.lists(
    st.text(min_size=1, max_size=20),
    min_size=0,
    max_size=5,
)

_confidence_st = st.floats(
    min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
)

_bool_st = st.booleans()

_endpoint_st = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Po", "Sm")),
    min_size=1,
    max_size=60,
)

_model_st = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Pd")),
    min_size=1,
    max_size=30,
)

_api_key_st = st.one_of(
    st.none(),
    st.text(min_size=1, max_size=50),
)

_taxonomy_st = st.lists(
    st.text(min_size=1, max_size=20),
    min_size=1,
    max_size=10,
)


def _make_base_config(source_dir: Path) -> Config:
    """Return a minimal valid Config to use as the file-sourced baseline."""
    return Config(
        source_dir=source_dir,
        target_dir=None,
        exclude_patterns=[],
        min_confidence=0.0,
        dry_run=False,
        ai_endpoint=_DEFAULT_AI_ENDPOINT,
        ai_model=_DEFAULT_AI_MODEL,
        ai_api_key=None,
        taxonomy=[],
    )


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

@given(
    base_path=_path_st,
    cli_source=_path_st,
)
@settings(max_examples=100)
def test_source_dir_cli_overrides_file(base_path: Path, cli_source: Path) -> None:
    """CLI source_dir overrides the config-file value.

    Validates: Requirements 10.2
    """
    base = _make_base_config(base_path)
    merged = base.merge_cli_overrides(source_dir=cli_source)
    assert merged.source_dir == cli_source


@given(
    base_path=_path_st,
    cli_target=_path_st,
)
@settings(max_examples=100)
def test_target_dir_cli_overrides_file(base_path: Path, cli_target: Path) -> None:
    """CLI target_dir overrides the config-file value.

    Validates: Requirements 10.2
    """
    base = _make_base_config(base_path)
    merged = base.merge_cli_overrides(target_dir=cli_target)
    assert merged.target_dir == cli_target


@given(
    base_path=_path_st,
    cli_patterns=_exclude_st.filter(lambda p: len(p) > 0),
)
@settings(max_examples=100)
def test_exclude_patterns_cli_overrides_file(
    base_path: Path, cli_patterns: list[str]
) -> None:
    """CLI exclude_patterns overrides the config-file value (non-empty list only).

    Validates: Requirements 10.2
    """
    base = _make_base_config(base_path)
    merged = base.merge_cli_overrides(exclude_patterns=cli_patterns)
    assert merged.exclude_patterns == cli_patterns


@given(
    base_path=_path_st,
    cli_conf=_confidence_st,
)
@settings(max_examples=100)
def test_min_confidence_cli_overrides_file(
    base_path: Path, cli_conf: float
) -> None:
    """CLI min_confidence overrides the config-file value.

    Validates: Requirements 10.2
    """
    base = _make_base_config(base_path)
    merged = base.merge_cli_overrides(min_confidence=cli_conf)
    assert merged.min_confidence == cli_conf


@given(
    base_path=_path_st,
    cli_dry=_bool_st,
)
@settings(max_examples=100)
def test_dry_run_cli_overrides_file(base_path: Path, cli_dry: bool) -> None:
    """CLI dry_run overrides the config-file value.

    Validates: Requirements 10.2
    """
    base = _make_base_config(base_path)
    merged = base.merge_cli_overrides(dry_run=cli_dry)
    assert merged.dry_run == cli_dry


@given(
    base_path=_path_st,
    cli_endpoint=_endpoint_st,
)
@settings(max_examples=100)
def test_ai_endpoint_cli_overrides_file(
    base_path: Path, cli_endpoint: str
) -> None:
    """CLI ai_endpoint overrides the config-file value.

    Validates: Requirements 10.2
    """
    base = _make_base_config(base_path)
    merged = base.merge_cli_overrides(ai_endpoint=cli_endpoint)
    assert merged.ai_endpoint == cli_endpoint


@given(
    base_path=_path_st,
    cli_model=_model_st,
)
@settings(max_examples=100)
def test_ai_model_cli_overrides_file(base_path: Path, cli_model: str) -> None:
    """CLI ai_model overrides the config-file value.

    Validates: Requirements 10.2
    """
    base = _make_base_config(base_path)
    merged = base.merge_cli_overrides(ai_model=cli_model)
    assert merged.ai_model == cli_model


@given(
    base_path=_path_st,
    cli_taxonomy=_taxonomy_st,
)
@settings(max_examples=100)
def test_taxonomy_cli_overrides_file(
    base_path: Path, cli_taxonomy: list[str]
) -> None:
    """CLI taxonomy overrides the config-file value.

    Validates: Requirements 10.2
    """
    base = _make_base_config(base_path)
    merged = base.merge_cli_overrides(taxonomy=cli_taxonomy)
    assert merged.taxonomy == cli_taxonomy


@given(
    base_path=_path_st,
    cli_source=_path_st,
    cli_conf=_confidence_st,
    cli_dry=_bool_st,
    cli_model=_model_st,
)
@settings(max_examples=100)
def test_multiple_cli_overrides_all_applied(
    base_path: Path,
    cli_source: Path,
    cli_conf: float,
    cli_dry: bool,
    cli_model: str,
) -> None:
    """When multiple CLI flags are provided, all of them override their config-file counterparts.

    Validates: Requirements 10.2
    """
    base = _make_base_config(base_path)
    merged = base.merge_cli_overrides(
        source_dir=cli_source,
        min_confidence=cli_conf,
        dry_run=cli_dry,
        ai_model=cli_model,
    )
    assert merged.source_dir == cli_source
    assert merged.min_confidence == cli_conf
    assert merged.dry_run == cli_dry
    assert merged.ai_model == cli_model


@given(
    base_path=_path_st,
)
@settings(max_examples=100)
def test_none_cli_values_do_not_override(base_path: Path) -> None:
    """CLI values that are None are treated as absent and do not overwrite file values.

    Validates: Requirements 10.2
    """
    original_target = Path("some/target")
    base = Config(
        source_dir=base_path,
        target_dir=original_target,
        exclude_patterns=["*.tmp"],
        min_confidence=0.5,
        dry_run=True,
        ai_endpoint="https://custom.endpoint/v1",
        ai_model="gpt-4",
        ai_api_key=None,
        taxonomy=["CustomCat"],
    )
    # Pass None for every optional parameter — none should be overridden
    merged = base.merge_cli_overrides(
        target_dir=None,
        ai_endpoint=None,
        ai_model=None,
        ai_api_key=None,
    )
    assert merged.target_dir == original_target
    assert merged.ai_endpoint == "https://custom.endpoint/v1"
    assert merged.ai_model == "gpt-4"
    assert merged.min_confidence == 0.5
    assert merged.dry_run is True
    assert merged.taxonomy == ["CustomCat"]


@given(
    base_path=_path_st,
    cli_source=_path_st,
)
@settings(max_examples=100)
def test_merge_returns_new_config_leaves_original_unchanged(
    base_path: Path, cli_source: Path
) -> None:
    """merge_cli_overrides returns a new Config; the original is not mutated.

    Validates: Requirements 10.2
    """
    base = _make_base_config(base_path)
    original_source = base.source_dir
    merged = base.merge_cli_overrides(source_dir=cli_source)
    # The merged config has the CLI value
    assert merged.source_dir == cli_source
    # The original is unchanged
    assert base.source_dir == original_source
