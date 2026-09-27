"""Canonical sorting destinations enforced at the write boundary."""

DESTINATION_OVERRIDES = {
    "Art/GAMES/BA/gaki": "Art/GAMES/BA",
}
ART_DESTINATION_PREFIX = "Art/"


def canonical_destination(folder_path: str) -> str:
    """Return the user-approved destination for a learned folder path."""
    return DESTINATION_OVERRIDES.get(folder_path, folder_path)


def is_art_destination(folder_path: str) -> bool:
    """Return whether a collection path is in the currently supported Art group."""
    return folder_path.startswith(ART_DESTINATION_PREFIX)


def is_image_destination(folder_path: str) -> bool:
    """Return whether a collection path belongs to the manual-only Image group."""
    return folder_path.partition("/")[0].casefold() == "image"
