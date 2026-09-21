"""Canonical sorting destinations enforced at the write boundary."""

DESTINATION_OVERRIDES = {
    "Art/GAMES/BA/gaki": "Art/GAMES/BA",
}


def canonical_destination(folder_path: str) -> str:
    """Return the user-approved destination for a learned folder path."""
    return DESTINATION_OVERRIDES.get(folder_path, folder_path)
