"""Pipeline orchestrator — Organizer class."""
# NOTE: Full implementation is deferred to task 14.1.
# This stub exposes the class so the CLI layer can import and call it.

from __future__ import annotations

from folder_organizer.config import Config
from folder_organizer.models import RunSummary


class Organizer:
    """Wires all pipeline stages together and executes them in order."""

    def __init__(self, config: Config) -> None:
        self.config = config

    def run(self) -> RunSummary:
        """Execute the full organizer pipeline.

        Returns a :class:`RunSummary` with counts for every outcome bucket.

        .. note::
            Full pipeline implementation is pending (task 14.1).
            This stub raises ``NotImplementedError`` so the CLI structure
            can be imported and tested without the downstream stages.
        """
        raise NotImplementedError(
            "Organizer.run() is not yet implemented. "
            "See task 14.1 for the full pipeline wiring."
        )
