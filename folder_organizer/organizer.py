"""Pipeline orchestrator — Organizer class."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

from folder_organizer.categorizer import AICategorizer
from folder_organizer.config import Config
from folder_organizer.discoverer import FileDiscoverer
from folder_organizer.file_mover import FileMover
from folder_organizer.folder_generator import FolderGenerator
from folder_organizer.inspector import FileInspector
from folder_organizer.logger import OrganizerLogger
from folder_organizer.metadata_store import MetadataStore
from folder_organizer.models import (
    CategorizedFile,
    CategorizationResult,
    InspectedFile,
    MetadataRecord,
    MoveResult,
    PlacedFile,
    RunSummary,
)


class Organizer:
    """Wires all pipeline stages together and executes them in order.

    Pipeline sequence:
    1. FileDiscoverer.discover  →  DiscoveryResult
    2. FileInspector.inspect    →  InspectedFile  (per file)
    3. AICategorizer.categorize →  CategorizationResult  (per file)
    4. [dry_run: print report and return]
    5. FolderGenerator.resolve_placement + create_folders
    6. FileMover.move           →  MoveResult  (per file)
    7. MetadataStore.upsert  →  MetadataStore.flush

    The MetadataStore is loaded at startup (step 0) before any categorization.
    OrganizerLogger is passed to stages for per-file progress and error logging.
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self._console = Console()

    def run(self) -> RunSummary:
        """Execute the full organizer pipeline.

        Returns a :class:`RunSummary` with counts for every outcome bucket.
        """
        config = self.config

        # ------------------------------------------------------------------
        # Resolve target directory (default to source_dir if unset)
        # ------------------------------------------------------------------
        source_dir: Path = config.source_dir
        target_dir: Path = config.target_dir if config.target_dir else source_dir

        # ------------------------------------------------------------------
        # Stage 0: Load MetadataStore
        # ------------------------------------------------------------------
        metadata_store = MetadataStore()
        metadata_store.load(target_dir)

        # ------------------------------------------------------------------
        # Stage 1: Discover files
        # ------------------------------------------------------------------
        discoverer = FileDiscoverer()
        discovery_result = discoverer.discover(source_dir, config.exclude_patterns)

        discovered_paths = discovery_result.discovered
        total_files = len(discovered_paths)

        # Report discovery counts (Requirement 2.4)
        self._console.print(
            f"[bold]Discovery:[/bold] {total_files} file(s) found, "
            f"{discovery_result.excluded_count} excluded, "
            f"{discovery_result.skipped_symlinks} symlink(s) skipped."
        )

        if total_files == 0:
            summary = RunSummary(
                total_discovered=0,
                total_processed=0,
                total_moved=0,
                total_skipped=0,
                total_review=0,
                total_unplaced=0,
                total_errors=0,
                dry_run=config.dry_run,
            )
            self._console.print("[yellow]No files to process.[/yellow]")
            return summary

        # ------------------------------------------------------------------
        # Initialise logger (also installs SIGINT handler)
        # ------------------------------------------------------------------
        with OrganizerLogger(
            target_dir=target_dir,
            total_files=total_files,
            metadata_store=metadata_store,
            console=self._console,
        ) as org_logger:

            # ------------------------------------------------------------------
            # Stage 2 + 3: Inspect and categorize each file
            # ------------------------------------------------------------------
            inspector = FileInspector()
            categorizer = AICategorizer(config=config, metadata_store=metadata_store)

            inspected_files: list[InspectedFile] = []
            categorized_files: list[CategorizedFile] = []

            for path in discovered_paths:
                # Inspect
                inspected = inspector.inspect(path)
                inspected_files.append(inspected)

                # Check if we should skip (same hash + category already in store)
                existing_record = metadata_store.get_by_hash(inspected.sha256)
                if existing_record is not None and metadata_store.should_skip(
                    inspected.sha256, existing_record.category
                ):
                    # Reuse existing record — count as skipped
                    cat_result = CategorizationResult(
                        category=existing_record.category,
                        subcategory=existing_record.subcategory,
                        confidence=existing_record.confidence_score,
                        method=existing_record.method,
                        review_required=existing_record.review_required,
                        fallback_used=existing_record.fallback_used,
                    )
                else:
                    # Categorize (AI or fallback)
                    cat_result = categorizer.categorize(inspected, existing_record)

                # Build CategorizedFile DTO
                cat_file = CategorizedFile(
                    path=inspected.path,
                    sha256=inspected.sha256,
                    size_bytes=inspected.size_bytes,
                    mime_type=inspected.mime_type,
                    extracted_text=inspected.extracted_text,
                    char_count=inspected.char_count,
                    extraction_status=str(inspected.extraction_status.value)
                    if hasattr(inspected.extraction_status, "value")
                    else str(inspected.extraction_status),
                    category=cat_result.category,
                    subcategory=cat_result.subcategory,
                    confidence=cat_result.confidence,
                    method=cat_result.method,
                    review_required=cat_result.review_required,
                    fallback_used=cat_result.fallback_used,
                )
                categorized_files.append(cat_file)

                org_logger.advance()

            # ------------------------------------------------------------------
            # Stage 4 (dry run): Print structured report and return
            # ------------------------------------------------------------------
            if config.dry_run:
                self._print_dry_run_report(categorized_files, target_dir)
                summary = RunSummary(
                    total_discovered=total_files,
                    total_processed=total_files,
                    total_moved=0,
                    total_skipped=0,
                    total_review=sum(1 for f in categorized_files if f.review_required),
                    total_unplaced=0,
                    total_errors=0,
                    dry_run=True,
                )
                org_logger.print_summary(summary)
                # Dry run: do NOT write organizer-metadata.json (Requirement 8.3)
                return summary

            # ------------------------------------------------------------------
            # Stage 5: Resolve placements and create folders
            # ------------------------------------------------------------------
            folder_generator = FolderGenerator()
            placements: list[PlacedFile] = [
                folder_generator.resolve_placement(cat_file, target_dir)
                for cat_file in categorized_files
            ]

            folder_errors = folder_generator.create_folders(placements)
            for ferr in folder_errors:
                org_logger.log_error(str(ferr.path), f"Folder creation failed: {ferr.reason}")
                org_logger.record_error()

            # ------------------------------------------------------------------
            # Stage 6 + 7: Move files, upsert metadata
            # ------------------------------------------------------------------
            file_mover = FileMover(dry_run=False)

            # Build a lookup from source_path → (cat_file, placed) for metadata upsert
            cat_map: dict[Path, CategorizedFile] = {f.path: f for f in categorized_files}

            for placed in placements:
                cat_file = cat_map[placed.source_path]
                move_result: MoveResult = file_mover.move(placed)

                # Determine the destination path string for the metadata record
                dest_path_str = (
                    str(move_result.destination_path)
                    if move_result.destination_path is not None
                    else ""
                )

                if move_result.success:
                    org_logger.log_action(
                        path=placed.source_path,
                        action="moved",
                        destination=move_result.destination_path or "",
                    )
                    if placed.review_required:
                        org_logger.record_review()
                    elif placed.unplaced:
                        org_logger.record_unplaced()
                    else:
                        org_logger.record_moved()
                else:
                    skip_reason = move_result.skip_reason or "unknown"
                    if skip_reason not in ("dry_run",):
                        org_logger.log_error(
                            path=placed.source_path,
                            reason=f"Move failed: {skip_reason}",
                        )
                        org_logger.record_error()

                # Upsert metadata record regardless of move outcome
                text_snippet = (cat_file.extracted_text or "")[:512]
                record = MetadataRecord(
                    original_path=str(cat_file.path.resolve()),
                    destination_path=dest_path_str,
                    sha256=cat_file.sha256,
                    size_bytes=cat_file.size_bytes,
                    mime_type=cat_file.mime_type,
                    text_snippet=text_snippet,
                    category=cat_file.category,
                    subcategory=cat_file.subcategory,
                    confidence_score=cat_file.confidence,
                    method=cat_file.method,
                    review_required=cat_file.review_required,
                    fallback_used=cat_file.fallback_used,
                    extraction_status=cat_file.extraction_status,
                    timestamp=_utc_now(),
                )
                metadata_store.upsert(record)

            # ------------------------------------------------------------------
            # Stage 7: Flush MetadataStore
            # ------------------------------------------------------------------
            metadata_store.flush(target_dir)

            # ------------------------------------------------------------------
            # Build and display final summary
            # ------------------------------------------------------------------
            summary = org_logger.build_partial_summary(dry_run=False)
            # Patch total_discovered in case the logger only knows processed count
            summary = RunSummary(
                total_discovered=total_files,
                total_processed=summary.total_processed,
                total_moved=summary.total_moved,
                total_skipped=summary.total_skipped,
                total_review=summary.total_review,
                total_unplaced=summary.total_unplaced,
                total_errors=summary.total_errors,
                dry_run=False,
            )
            org_logger.print_summary(summary)

        return summary

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _print_dry_run_report(
        self,
        categorized_files: list[CategorizedFile],
        target_dir: Path,
    ) -> None:
        """Print the dry-run report table (Requirement 8.2, 8.4).

        Lists each file with its proposed destination, category, subcategory,
        confidence score, and any ``_review`` / ``_unplaced`` flags.
        """
        self._console.print()
        table = Table(
            title="[bold yellow]DRY RUN — Proposed Changes (no files moved)[/bold yellow]",
            show_header=True,
            show_lines=False,
        )
        table.add_column("File", style="cyan", no_wrap=False, max_width=40)
        table.add_column("Proposed Destination", style="green", no_wrap=False, max_width=40)
        table.add_column("Category", style="magenta")
        table.add_column("Subcategory", style="blue")
        table.add_column("Conf.", justify="right")
        table.add_column("Flags", justify="left")

        folder_generator = FolderGenerator()

        for cat_file in categorized_files:
            # Resolve destination path (same logic as real run)
            placed = folder_generator.resolve_placement(cat_file, target_dir)

            proposed_dest = str(placed.destination_dir / cat_file.path.name)

            flags: list[str] = []
            if cat_file.review_required:
                flags.append("_review")
            if placed.unplaced:
                flags.append("_unplaced")
            flags_str = ", ".join(flags) if flags else "—"

            table.add_row(
                cat_file.path.name,
                proposed_dest,
                cat_file.category,
                cat_file.subcategory or "—",
                f"{cat_file.confidence:.2f}",
                flags_str,
            )

        self._console.print(table)
        self._console.print()


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _utc_now() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
