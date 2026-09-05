"""Entry point for ``python -m folder_organizer``.

Delegates directly to the Typer application defined in :mod:`folder_organizer.cli`.
"""

from folder_organizer.cli import app

if __name__ == "__main__":
    app()
