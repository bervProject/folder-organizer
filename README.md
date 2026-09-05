# folder-organizer

AI-powered local file organizer for categorizing and sorting files into folders based on content and metadata.

## Current status

This project is currently in an early implementation stage. The package includes:

- a Typer-based CLI entry point
- YAML/JSON configuration loading and validation
- default category taxonomy definitions
- shared data models for pipeline stages and metadata persistence
- project scaffolding for the organizer pipeline

The actual end-to-end file discovery, inspection, AI categorization, folder creation, moving logic, and metadata writing are not implemented yet. The orchestrator currently raises a `NotImplementedError` in `folder_organizer/organizer.py`, which is consistent with the repository's early-stage task plan.

## What is implemented today

### CLI

The CLI is available through:

- `python -m folder_organizer`
- `folder-organizer` after installation

Example usage:

```bash
python -m folder_organizer "C:/path/to/source" --target-dir "C:/path/to/organized"
python -m folder_organizer "C:/path/to/source" --dry-run --min-confidence 0.6
python -m folder_organizer "C:/path/to/source" --config config.yaml
```

Supported options:

- `source_dir` (required positional argument)
- `--target-dir, -t`
- `--config, -c`
- `--exclude, -e` (repeatable)
- `--min-confidence`
- `--dry-run / --no-dry-run`
- `--ai-endpoint`
- `--ai-model`

The CLI validates that the source directory exists and is a directory before invoking the organizer pipeline.

### Configuration

The project supports YAML or JSON config files with a required `source_dir` field.

Example YAML:

```yaml
source_dir: /path/to/source
target_dir: /path/to/organized
exclude_patterns:
  - "*.tmp"
  - "__pycache__/**"
min_confidence: 0.6
dry_run: true
ai_endpoint: https://api.openai.com/v1/chat/completions
ai_model: gpt-4o-mini
taxonomy:
  - Finance
  - Legal
```

Example JSON:

```json
{
  "source_dir": "/path/to/source",
  "target_dir": "/path/to/organized",
  "exclude_patterns": ["*.tmp", "__pycache__/**"],
  "min_confidence": 0.6,
  "dry_run": true,
  "ai_endpoint": "https://api.openai.com/v1/chat/completions",
  "ai_model": "gpt-4o-mini",
  "taxonomy": ["Finance", "Legal"]
}
```

Config precedence is:

1. config file values
2. CLI overrides
3. defaults

### Default taxonomy

The default taxonomy includes these categories:

- Documents
- Images
- Videos
- Audio
- Code
- Archives
- Finance
- Data
- Presentations
- Spreadsheets
- Executables
- Fonts
- Uncategorized

Additional labels can be merged by the project using the `build_taxonomy()` helper.

## Project structure

```text
folder_organizer/
  __init__.py
  __main__.py
  categorizer.py
  cli.py
  config.py
  discoverer.py
  inspector.py
  file_mover.py
  folder_generator.py
  logger.py
  metadata_store.py
  models.py
  organizer.py
  taxonomy.py

tests/
  integration/
  property/
  unit/
```

## Installation

From the project root:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

## Development notes

The project is designed around a staged pipeline model:

- discovery of files
- inspection of file metadata and contents
- categorization with AI or fallback heuristics
- folder generation
- file moves and review handling
- metadata persistence

At present, the repository contains the scaffolding and validation runtime for the CLI and configuration layer, but the actual organizer pipeline is not yet active.

## Verified behavior

The CLI and entry points were checked from the source tree with:

```bash
python -m folder_organizer --help
```

This confirms the application currently exposes the command-line interface described above.

## Roadmap

Planned work in the project includes:

- file discovery and exclusion logic
- MIME inspection and content extraction
- AI-based categorization and confidence thresholds
- destination folder generation and move execution
- metadata persistence and run summaries
- full integration test coverage for the pipeline

## License

This project is licensed under the MIT license. See `LICENSE` for details.
