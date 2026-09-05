# Implementation Plan: Local File Organizer

## Overview

Implement the Local File Organizer as a Python CLI application following a linear pipeline architecture: discover → inspect → categorize → generate folders → move. Each stage is an independent module with well-defined input/output data structures. The pipeline orchestrator wires all stages together and handles dry-run short-circuiting. Testing is layered: unit tests per module, property-based tests (Hypothesis) for all 19 correctness properties, and integration tests for end-to-end flows.

## Tasks

- [x] 1. Project scaffolding and package structure
  - [x] 1.1 Create the `folder_organizer` package and project layout
    - Create `folder_organizer/` directory with an empty `__init__.py`
    - Create stub module files: `__main__.py`, `cli.py`, `config.py`, `organizer.py`, `discoverer.py`, `inspector.py`, `categorizer.py`, `folder_generator.py`, `file_mover.py`, `metadata_store.py`, `logger.py`, `models.py`, `taxonomy.py`
    - Create `tests/` with subdirectories `tests/unit/`, `tests/property/`, `tests/integration/` each containing an `__init__.py`
    - _Requirements: all — establishes the foundation every other task builds on_

  - [x] 1.2 Create `pyproject.toml` with all dependencies pinned
    - Define build system (`hatchling` or `setuptools`), project name `folder-organizer`, Python `>=3.11`
    - Add runtime dependencies: `typer`, `rich`, `pypdf`, `python-docx`, `openpyxl`, `python-pptx`, `python-magic`, `openai`, `PyYAML`
    - Add dev/test dependencies: `pytest`, `pytest-tmp-path`, `hypothesis`, `responses`, `unittest-mock`
    - Add `[project.scripts]` entry point `folder-organizer = folder_organizer.cli:app`
    - _Requirements: 10.1 (configuration), 3.x (extraction libraries), 4.x (AI SDK)_

---

- [x] 2. Shared data models and taxonomy
  - [x] 2.1 Implement `models.py` — all pipeline DTOs and `MetadataRecord`
    - Define `ExtractionStatus` enum: `OK`, `UNAVAILABLE`, `FAILED`
    - Define `MetadataRecord` dataclass with all fields from design: `original_path`, `destination_path`, `sha256`, `size_bytes`, `mime_type`, `text_snippet`, `category`, `subcategory`, `confidence_score`, `method`, `review_required`, `fallback_used`, `extraction_status`, `timestamp`
    - Define `DiscoveredFile`, `InspectedFile`, `CategorizedFile`, `PlacedFile`, `MoveResult`, `FolderCreationError`, `RunSummary` dataclasses
    - Implement `MetadataRecord` serialization to/from `dict` (using `dataclasses.asdict`) and JSON round-trip helpers
    - _Requirements: 5.2 (all MetadataRecord fields), 9.3 (RunSummary)_

  - [x] 2.2 Write property test for MetadataRecord round-trip fidelity
    - **Property 1: Metadata round-trip fidelity**
    - Generate arbitrary `MetadataRecord` instances with Hypothesis `@given` strategies; assert `deserialize(serialize(r)) == r` for all generated values
    - Tag: `# Feature: local-file-organizer, Property 1: Metadata round-trip fidelity`
    - **Validates: Requirements 5.2, 5.3**

  - [x] 2.3 Implement `taxonomy.py` — default category list and taxonomy validation
    - Define `DEFAULT_TAXONOMY` list with all 13 built-in categories from design
    - Implement `build_taxonomy(user_additions: list[str]) -> frozenset[str]` that merges default and user-configured values
    - _Requirements: 4.7 (taxonomy validation), 10.1 (user-extendable taxonomy)_

---

- [x] 3. Configuration layer
  - [x] 3.1 Implement `config.py` — `Config` dataclass and `ConfigLoader`
    - Define `Config` dataclass with all fields: `source_dir`, `target_dir`, `exclude_patterns`, `min_confidence`, `dry_run`, `ai_endpoint`, `ai_model`, `ai_api_key`, `taxonomy`
    - Implement `ConfigLoader.load(path: Path) -> Config` that reads YAML or JSON, raises `ConfigParseError(path, line, message)` on syntax errors with line/position info
    - Implement `Config.merge_cli_overrides(**kwargs) -> Config` that applies CLI values on top of file values (CLI wins on every present flag)
    - Validate `min_confidence` is in [0.0, 1.0]; raise descriptive error otherwise
    - _Requirements: 10.1, 10.2, 10.3, 10.5_

  - [x] 3.2 Write property test for CLI flags overriding config file values
    - **Property 19: CLI flags override config file values**
    - Generate arbitrary `(config_value, cli_value)` pairs for each overridable parameter; assert `merged_config` uses `cli_value` for every parameter passed as a CLI override
    - Tag: `# Feature: local-file-organizer, Property 19: CLI flags override config file values`
    - **Validates: Requirements 10.2**

  - [x] 3.3 Write unit tests for `ConfigLoader`
    - Test loading valid YAML config, valid JSON config
    - Test `ConfigParseError` raised for malformed YAML with correct line/position
    - Test missing `source_dir` raises descriptive error
    - Test `min_confidence` out-of-range raises error
    - _Requirements: 10.1, 10.3, 10.5_

---

- [x] 4. CLI layer
  - [x] 4.1 Implement `cli.py` — Typer app with all flags
    - Define `app = typer.Typer()` and `organize` command with all parameters from design: `source_dir`, `target_dir`, `config_file`, `exclude`, `min_confidence`, `dry_run`, `ai_endpoint`, `ai_model`
    - Load config file via `ConfigLoader.load` when `--config` is provided; merge CLI overrides on top
    - Validate `source_dir` exists and is a directory; exit code 1 with descriptive error otherwise
    - Validate `target_dir` (create if missing, exit code 1 if creation fails)
    - Call `Organizer(config).run()` after validation
    - Implement `--help` via Typer's auto-generated help (ensure all options have `help=` strings with types and defaults)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 10.1, 10.2, 10.4, 10.5_

  - [x] 4.2 Implement `__main__.py` entry point
    - Single call to `app()` from `cli.py` so `python -m folder_organizer` works
    - _Requirements: 10.4_

  - [x] 4.3 Write unit tests for `cli.py` validation logic
    - Test non-existent `source_dir` → exit code 1, no file I/O
    - Test `source_dir` pointing to a file → exit code 1
    - Test missing `source_dir` with no config → descriptive error, exit code 1
    - Test `target_dir` creation on non-existent path
    - _Requirements: 1.1, 1.2, 1.4, 1.5, 10.5_

---

- [x] 5. File Discoverer
  - [x] 5.1 Implement `discoverer.py` — recursive enumeration with exclusion and symlink handling
    - Implement `FileDiscoverer.discover(source_dir: Path, exclude_patterns: list[str]) -> DiscoveryResult`
    - Use `pathlib.Path.rglob("*")` for recursive enumeration
    - Skip symlinks whose `path.resolve()` does not start with `source_dir.resolve()` (canonical absolute path check); increment `skipped_symlinks`
    - Apply `fnmatch.fnmatch` against relative path string for each exclusion pattern; increment `excluded_count` on match
    - Only yield regular files (`path.is_file()`)
    - Raise `DiscoveryError` with path and reason if `source_dir` is not readable
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 5.2 Write property test for recursive enumeration completeness
    - **Property 12: Recursive enumeration discovers all files**
    - Generate arbitrary directory trees of varying depth (using `tmp_path` + Hypothesis); assert discovered list equals ground-truth `set(p for p in source_dir.rglob("*") if p.is_file())`
    - Tag: `# Feature: local-file-organizer, Property 12: Recursive enumeration discovers all files`
    - **Validates: Requirements 2.1**

  - [x] 5.3 Write property test for exclusion filter correctness
    - **Property 13: Exclusion filter removes all matching files**
    - Generate arbitrary file path lists and glob patterns; assert no file whose relative path matches any pattern appears in the result
    - Tag: `# Feature: local-file-organizer, Property 13: Exclusion filter removes all matching files`
    - **Validates: Requirements 2.2**

  - [x] 5.4 Write property test for discovery count accuracy
    - **Property 14: Discovery count report is accurate**
    - Generate temp directories with known files including some matching exclusion patterns; assert `discovered + excluded + skipped_symlinks` equals total paths encountered
    - Tag: `# Feature: local-file-organizer, Property 14: Discovery count report is accurate`
    - **Validates: Requirements 2.4**

  - [x] 5.5 Write unit tests for `FileDiscoverer`
    - Test out-of-scope symlink is skipped and counted
    - Test discovery report output format (counts reported before proceeding)
    - Test `DiscoveryError` on unreadable directory
    - _Requirements: 2.3, 2.4, 2.5_

---

- [x] 6. File Inspector
  - [x] 6.1 Implement `inspector.py` — MIME detection, text extraction, SHA-256
    - Implement `FileInspector.inspect(path: Path) -> InspectedFile`
    - Compute SHA-256 over full binary content via `hashlib.sha256`; always store in record even if extraction fails
    - Detect MIME type using `python-magic`; fall back to `mimetypes.guess_type` if magic is unavailable
    - Dispatch to extractor based on MIME type / extension:
      - `text/*`: read raw bytes, decode UTF-8 with `errors="replace"`, truncate to 4,096 chars
      - `application/pdf`: use `pypdf.PdfReader`, extract text from first 10 pages
      - `.docx`: use `python-docx`, join all paragraph texts, truncate to 4,096 chars
      - `.xlsx`: use `openpyxl`, join all cell values across all sheets, truncate to 4,096 chars
      - `.pptx`: use `python-pptx`, join all slide text frames, truncate to 4,096 chars
      - All other formats: set `extraction_status = ExtractionStatus.UNAVAILABLE`
    - On read error or processing exception: set `extraction_status = ExtractionStatus.FAILED`; continue
    - Store `char_count = len(extracted_text)` when extraction succeeds
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

  - [x] 6.2 Write property test for SHA-256 correctness
    - **Property 15: SHA-256 hash is computed correctly**
    - Generate arbitrary bytes content; write to `tmp_path`; assert `inspector.inspect(path).sha256 == hashlib.sha256(content).hexdigest()`
    - Tag: `# Feature: local-file-organizer, Property 15: SHA-256 hash is computed correctly`
    - **Validates: Requirements 3.5**

  - [x] 6.3 Write property test for extraction char count bounds
    - **Property 8: Extraction character count is within bounds**
    - Generate text content of varying length (including > 4,096 chars); assert `0 <= char_count <= 4096` and `char_count == len(extracted_text)`
    - Tag: `# Feature: local-file-organizer, Property 8: Extraction character count is within bounds`
    - **Validates: Requirements 3.1, 3.7**

  - [x] 6.4 Write unit tests for `FileInspector`
    - Test PDF extraction from first 10 pages (mock `pypdf`)
    - Test `.docx`, `.xlsx`, `.pptx` extraction (mock respective libraries)
    - Test binary file returns `UNAVAILABLE` status
    - Test read error sets `extraction_status = FAILED` and does not raise
    - Test `MIME` fallback when `python-magic` is unavailable
    - _Requirements: 3.2, 3.3, 3.4, 3.6_

---

- [x] 7. Checkpoint — ensure scaffolding, models, config, CLI, discoverer, and inspector tests pass
  - Ensure all tests pass, ask the user if questions arise.

---

- [~] 8. AI Categorizer
  - [-] 8.1 Implement `categorizer.py` — OpenAI structured outputs and fallback chain
    - Implement `AICategorizer.categorize(file: InspectedFile, existing_record: Optional[MetadataRecord]) -> CategorizationResult`
    - Before calling AI: check `MetadataStore` for existing record with matching `sha256`; reuse if found and not stale (Requirement 5.7)
    - Assemble prompt using `extracted_text`, `filename`, `extension`, `size_bytes`, `mime_type` and the full taxonomy list
    - Call OpenAI API with `response_format={"type": "json_schema", ...}` using the schema from design
    - Validate returned `category` against taxonomy via `_is_valid_category`; if invalid: `review_required = True`, skip auto-move
    - If `confidence < min_confidence`: set `review_required = True`
    - Implement `_fallback_categorize`: map extension to category; set `fallback_used = True`, `confidence = 0.0`
    - If AI fails AND extension absent/unrecognized: assign `"Uncategorized"`, `fallback_used = True`, `review_required = True`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_

  - [-] 8.2 Write property test for confidence score range
    - **Property 2: Confidence score is always in range**
    - Generate arbitrary file signals through the categorizer with mocked AI responses returning arbitrary floats; assert `0.0 <= result.confidence <= 1.0` for all AI and fallback paths
    - Tag: `# Feature: local-file-organizer, Property 2: Confidence score is always in range`
    - **Validates: Requirements 4.2, 4.6**

  - [-] 8.3 Write property test for duplicate file deduplication
    - **Property 4: Duplicate files reuse existing categorization**
    - Generate two `InspectedFile` instances with identical `sha256`; process the first, seed the metadata store; process the second; assert AI is not called again and result matches first
    - Tag: `# Feature: local-file-organizer, Property 4: Duplicate files reuse existing categorization`
    - **Validates: Requirements 4.5, 5.5**

  - [-] 8.4 Write property test for non-empty category assignment
    - **Property 16: Every processed file is assigned a non-empty category**
    - Generate arbitrary `InspectedFile` instances through all categorizer paths (AI, fallback, uncategorized); assert `result.category` is always a non-empty string and `subcategory` is non-empty string or `None`
    - Tag: `# Feature: local-file-organizer, Property 16: Every processed file is assigned a non-empty category`
    - **Validates: Requirements 4.1**

  - [-] 8.5 Write unit tests for `AICategorizer`
    - Test successful AI call returns correct `CategorizationResult`
    - Test out-of-taxonomy AI response triggers `review_required = True`
    - Test AI unavailable → `_fallback_categorize` used, `fallback_used = True`, `confidence = 0.0`
    - Test AI unavailable + unknown extension → `"Uncategorized"`, `review_required = True`
    - Test `confidence < min_confidence` → `review_required = True`
    - Test duplicate `sha256` skips AI call
    - _Requirements: 4.1, 4.3, 4.5, 4.6, 4.7, 4.8_

---

- [ ] 9. Folder Generator
  - [ ] 9.1 Implement `folder_generator.py` — placement resolution and name sanitization
    - Implement `FolderGenerator.resolve_placement(file: CategorizedFile, target_dir: Path) -> PlacedFile`
    - Route `review_required=True` files to `target_dir/_review/`
    - Build destination path: `target_dir / sanitize(category) / sanitize(subcategory)` (subcategory level optional)
    - Implement `FolderGenerator.create_folders(placements: list[PlacedFile]) -> list[FolderCreationError]`
    - Use `Path.mkdir(parents=True, exist_ok=True)`; on `PermissionError` log error and route file to `_unplaced`
    - Implement `FolderGenerator.sanitize_name(label: str) -> str`: replace any character not in `[A-Za-z0-9_\-. ]` with `_`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [ ]* 9.2 Write property test for sanitize_name idempotency
    - **Property 6: Folder name sanitization is idempotent**
    - Generate arbitrary Unicode strings with Hypothesis; assert `sanitize_name(sanitize_name(s)) == sanitize_name(s)`
    - Tag: `# Feature: local-file-organizer, Property 6: Folder name sanitization is idempotent`
    - **Validates: Requirements 6.3**

  - [ ]* 9.3 Write unit tests for `FolderGenerator`
    - Test category folder created at correct path
    - Test subcategory subfolder created inside category folder
    - Test `review_required` file routed to `_review/`
    - Test existing folder reused without error
    - Test permission error routes file to `_unplaced/`
    - _Requirements: 6.1, 6.2, 6.4, 6.5_

---

- [ ] 10. File Mover
  - [ ] 10.1 Implement `file_mover.py` — move with conflict resolution and mtime preservation
    - Implement `FileMover.move(placed: PlacedFile) -> MoveResult`
    - Use `shutil.move` to move file to destination directory
    - After move, restore original `mtime` via `os.utime(destination, (atime, original_mtime))`
    - Implement `FileMover._resolve_conflict(dest_dir: Path, filename: str) -> Optional[Path]`: append `_1` through `_9999` before extension until unique name found; return `None` if all 9,999 exhausted
    - On `PermissionError` or `OSError`: log error with file path and reason, return `MoveResult(success=False)`; continue processing
    - When `_resolve_conflict` returns `None`: log error, skip file, continue
    - If `dry_run=True`: compute resolved destination path without performing any I/O; return `MoveResult` with path but `success=False` (no actual move)
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

  - [ ]* 10.2 Write property test for conflict resolution uniqueness
    - **Property 5: Conflict resolution always produces a unique destination name**
    - Generate lists of files sharing the same base name (up to 9,999); move each into the same `tmp_path` directory; assert all destination paths are distinct and no two files share a path
    - Tag: `# Feature: local-file-organizer, Property 5: Conflict resolution always produces a unique destination name`
    - **Validates: Requirements 7.2, 7.6**

  - [ ]* 10.3 Write property test for mtime preservation
    - **Property 11: File last-modified timestamp is preserved after move**
    - Generate arbitrary files with arbitrary `mtime` values set via `os.utime`; move each file; assert `os.stat(destination).st_mtime == original_mtime`
    - Tag: `# Feature: local-file-organizer, Property 11: File last-modified timestamp is preserved after move`
    - **Validates: Requirements 7.3**

  - [ ]* 10.4 Write unit tests for `FileMover`
    - Test file moved to correct destination
    - Test conflict suffix appended correctly (`report_1.pdf`, `report_2.pdf`, ...)
    - Test suffix exhaustion at 9,999 logs error and skips file
    - Test permission error logs error, skips file, continues
    - Test dry run returns resolved path without I/O
    - _Requirements: 7.1, 7.2, 7.4, 7.6_

---

- [ ] 11. Metadata Store
  - [ ] 11.1 Implement `metadata_store.py` — load, upsert, merge, and atomic flush
    - Implement `MetadataStore.load(target_dir: Path) -> None`: read `organizer-metadata.json` if present; populate in-memory dict keyed by `original_path` and secondary index by `sha256`
    - Implement `MetadataStore.get_by_hash(sha256: str) -> Optional[MetadataRecord]`
    - Implement `MetadataStore.get_by_path(path: Path) -> Optional[MetadataRecord]`
    - Implement `MetadataStore.upsert(record: MetadataRecord) -> None`: insert or overwrite by `original_path`; update `sha256` index
    - Implement `MetadataStore.flush(target_dir: Path) -> None`: serialize all records to `{"version": "1", "records": {...}}` JSON; write to temp file in same directory; atomically rename to `organizer-metadata.json`; on failure log error and retain in-memory records without aborting
    - Implement merge logic: on `load`, existing records not in current run are preserved (keyed by path)
    - Skip re-processing if `sha256` matches and `category` is the same (Requirement 5.5); re-process and overwrite if `sha256` matches but `category` differs (Requirement 5.7)
    - _Requirements: 5.1, 5.3, 5.4, 5.5, 5.6, 5.7_

  - [ ]* 11.2 Write property test for metadata merge preserving existing records
    - **Property 7: Metadata merge preserves existing records**
    - Generate two disjoint sets of `MetadataRecord` instances; load the first set, simulate a merge with the second set; assert all records from the first set are still present in the store after merge
    - Tag: `# Feature: local-file-organizer, Property 7: Metadata merge preserves existing records`
    - **Validates: Requirements 5.6**

  - [ ]* 11.3 Write unit tests for `MetadataStore`
    - Test load of existing `organizer-metadata.json` populates records correctly
    - Test upsert overwrites existing record by path
    - Test flush writes `organizer-metadata.json` atomically (temp file → rename)
    - Test flush failure logs error but does not abort run
    - Test skip re-processing when `sha256` + `category` match (Requirement 5.5)
    - Test overwrite when `sha256` matches but `category` differs (Requirement 5.7)
    - _Requirements: 5.3, 5.4, 5.5, 5.6, 5.7_

---

- [ ] 12. Logger and Progress Reporter
  - [ ] 12.1 Implement `logger.py` — Rich progress, JSON-Lines log, SIGINT handler
    - Implement `OrganizerLogger` wrapping `Rich`'s `Progress` for the live progress indicator (files processed / total)
    - Configure a `logging.FileHandler` writing to `target_dir/organizer.log` with a JSON-Lines formatter
    - Each log entry format: `{"timestamp": "<ISO8601>", "level": "INFO|WARN|ERROR", "path": "...", "action": "...", "destination": "..."}`
    - Implement `OrganizerLogger.log_action(path, action, destination, level)` and `log_error(path, reason)`
    - Install a `SIGINT` signal handler that calls `metadata_store.flush()` and prints a partial `RunSummary` before exiting with code 130
    - _Requirements: 9.1, 9.2, 9.4, 9.5_

  - [ ]* 12.2 Write property test for structured log entry completeness
    - **Property 17: Structured log entries contain all required fields**
    - Process arbitrary sets of files (mocked pipeline); parse each line of `organizer.log`; assert every entry contains valid ISO 8601 `timestamp`, `level` in `{INFO, WARN, ERROR}`, non-empty `path`, non-empty `action`
    - Tag: `# Feature: local-file-organizer, Property 17: Structured log entries contain all required fields`
    - **Validates: Requirements 9.2, 9.5**

  - [ ]* 12.3 Write unit tests for `OrganizerLogger`
    - Test progress indicator increments correctly
    - Test log entry written with all required fields for INFO, WARN, ERROR levels
    - Test ISO 8601 timestamp format in log entries
    - _Requirements: 9.1, 9.2, 9.5_

---

- [ ] 13. Checkpoint — ensure all component tests pass before pipeline wiring
  - Ensure all tests pass, ask the user if questions arise.

---

- [ ] 14. Pipeline Orchestrator
  - [ ] 14.1 Implement `organizer.py` — pipeline wiring and dry-run short-circuit
    - Implement `Organizer(config: Config)` class with `run() -> RunSummary`
    - Stage sequence: `FileDiscoverer.discover` → `FileInspector.inspect` (per file) → `AICategorizer.categorize` (per file) → if `dry_run`: print structured report and return; else: `FolderGenerator.resolve_placement` + `FolderGenerator.create_folders` → `FileMover.move` (per file) → `MetadataStore.upsert` → `MetadataStore.flush`
    - Load existing `MetadataStore` at startup before categorization begins
    - Pass `OrganizerLogger` to each stage for per-file progress updates and error logging
    - Dry-run report: table via Rich listing file, proposed destination, category, subcategory, confidence, `_review`/`_unplaced` flags
    - Dry run does NOT write `organizer-metadata.json` (Requirement 8.3)
    - Collect `RunSummary` counts as stages complete; display final summary on completion
    - _Requirements: 1.3, 1.4, 2.4, 8.1, 8.2, 8.3, 8.4, 9.1, 9.3_

  - [ ]* 14.2 Write property test for below-threshold files never auto-moved
    - **Property 3: Below-threshold files are never auto-moved**
    - Generate `(threshold, confidence)` pairs where `confidence < threshold`; run mocked pipeline; assert file is routed to `_review/`, not a category folder
    - Tag: `# Feature: local-file-organizer, Property 3: Below-threshold files are never auto-moved`
    - **Validates: Requirements 4.3, 7.5**

  - [ ]* 14.3 Write property test for every processed file having a complete MetadataRecord
    - **Property 10: Every processed file has a complete MetadataRecord**
    - Generate arbitrary sets of `InspectedFile` instances; after processing through mocked pipeline stages, assert every file has a `MetadataRecord` with all required fields populated with correct types
    - Tag: `# Feature: local-file-organizer, Property 10: Every processed file has a complete MetadataRecord`
    - **Validates: Requirements 5.1, 5.2**

  - [ ]* 14.4 Write property test for run summary count accuracy
    - **Property 18: Run summary counts match actual operation counts**
    - Run pipeline over known sets of files with predetermined mock outcomes; assert `RunSummary.total_moved`, `total_skipped`, `total_review`, `total_unplaced`, `total_errors` equal the true counts of files in each outcome bucket
    - Tag: `# Feature: local-file-organizer, Property 18: Run summary counts match actual operation counts`
    - **Validates: Requirements 9.3**

  - [ ]* 14.5 Write unit tests for `Organizer`
    - Test dry run does not create folders, move files, or write metadata
    - Test dry run output report lists all files with correct proposed destinations
    - Test `_review` files appear in dry-run report with correct flag
    - Test `_unplaced` files appear in dry-run report with correct flag
    - Test SIGINT flushes metadata and prints partial summary
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 9.4_

---

- [ ] 15. Property-based tests for remaining properties
  - [ ] 15.1 Write property test for dry run producing zero disk mutations
    - **Property 9: Dry run produces zero disk mutations**
    - Generate a temp directory with arbitrary file names and contents; snapshot the directory state; run the full pipeline with `dry_run=True` (mocked AI); take a second snapshot; assert the two snapshots are identical (no files moved, no folders created, no `organizer-metadata.json` written)
    - Tag: `# Feature: local-file-organizer, Property 9: Dry run produces zero disk mutations`
    - **Validates: Requirements 8.1, 8.3**

---

- [ ] 16. Integration tests
  - [ ] 16.1 Write integration test — full pipeline with mixed file types
    - Create a synthetic `tmp_path` directory with text files, a PDF stub, an image, and a binary file
    - Mock the OpenAI API via `responses` library to return valid categorization results
    - Run `Organizer.run()` end-to-end; assert all files are moved to correct category folders, `organizer-metadata.json` is written with all records, `organizer.log` is created
    - _Requirements: 1.x, 2.x, 3.x, 4.x, 5.x, 6.x, 7.x, 9.x_

  - [ ] 16.2 Write integration test — metadata persistence and reload across two runs
    - Run the pipeline over a set of files; record the `organizer-metadata.json`
    - Run the pipeline again over the same directory; assert previously processed files are skipped (reuse existing records), new files are added, and no existing records are removed
    - _Requirements: 5.5, 5.6, 5.7_

  - [ ] 16.3 Write integration test — AI service failure with fallback categorization
    - Mock the OpenAI API to return a 503 error; run the pipeline; assert all files receive extension-based fallback categories, `fallback_used = True`, `confidence = 0.0` in all records
    - _Requirements: 4.6, 4.8_

  - [ ] 16.4 Write integration test — dry run produces zero mutations
    - Snapshot directory state; run with `dry_run=True`; assert directory state is unchanged and `organizer-metadata.json` is not written
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [ ] 16.5 Write integration test — SIGINT produces partial metadata flush
    - Start a run over a large synthetic directory; inject `SIGINT` mid-run using `os.kill`; assert `organizer-metadata.json` contains records for all files processed up to the interrupt point and a partial summary is printed
    - _Requirements: 9.4_

  - [ ] 16.6 Write integration test — AI returns out-of-taxonomy category
    - Mock the OpenAI API to return a category not in the taxonomy; assert the affected files are routed to `_review/`, `review_required = True` in their records, and no file is moved to a category folder
    - _Requirements: 4.7_

---

- [ ] 17. Final checkpoint — ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP implementation
- Each task references specific requirements for full traceability
- The pipeline is deliberately linear; do not introduce cross-stage calls
- AI API calls in unit and property tests must always be mocked via `unittest.mock.patch` or `responses`; real network calls are only permitted in integration tests when explicitly documented
- Property tests use Hypothesis with a minimum of 100 iterations per test
- The `MetadataStore` uses atomic write (temp file → rename) to prevent corruption on interrupt
- The `_review` and `_unplaced` folders are created on demand; do not pre-create them at startup
- All file-system operations in tests use `pytest`'s `tmp_path` fixture

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1", "2.3"] },
    { "id": 2, "tasks": ["2.2", "3.1"] },
    { "id": 3, "tasks": ["3.2", "3.3", "4.1", "4.2"] },
    { "id": 4, "tasks": ["4.3", "5.1"] },
    { "id": 5, "tasks": ["5.2", "5.3", "5.4", "5.5", "6.1"] },
    { "id": 6, "tasks": ["6.2", "6.3", "6.4", "8.1"] },
    { "id": 7, "tasks": ["8.2", "8.3", "8.4", "8.5", "9.1"] },
    { "id": 8, "tasks": ["9.2", "9.3", "10.1"] },
    { "id": 9, "tasks": ["10.2", "10.3", "10.4", "11.1"] },
    { "id": 10, "tasks": ["11.2", "11.3", "12.1"] },
    { "id": 11, "tasks": ["12.2", "12.3", "14.1"] },
    { "id": 12, "tasks": ["14.2", "14.3", "14.4", "14.5"] },
    { "id": 13, "tasks": ["15.1"] },
    { "id": 14, "tasks": ["16.1", "16.2", "16.3", "16.4", "16.5", "16.6"] }
  ]
}
```
