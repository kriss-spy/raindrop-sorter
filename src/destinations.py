"""Canonical sorting destinations enforced at the write boundary."""

DESTINATION_OVERRIDES = {
    "Art/GAMES/BA/gaki": "Art/GAMES/BA",
}
ART_DESTINATION_PREFIX = "Art/"
MANUAL_ASSIGNMENT_DESTINATION_GROUPS = frozenset({"art", "image", "video"})
MANUAL_ONLY_DESTINATION_GROUPS = frozenset({"image", "video"})


def canonical_destination(folder_path: str) -> str:
    """Return the user-approved destination for a learned folder path."""
    return DESTINATION_OVERRIDES.get(folder_path, folder_path)


def is_art_destination(folder_path: str) -> bool:
    """Return whether a collection path is in the currently supported Art group."""
    return folder_path.startswith(ART_DESTINATION_PREFIX)


def _destination_group(folder_path: str) -> str:
    return folder_path.partition("/")[0].casefold()


def is_manual_assignment_destination(folder_path: str) -> bool:
    """Return whether a live collection may be chosen during manual review."""
    return _destination_group(folder_path) in MANUAL_ASSIGNMENT_DESTINATION_GROUPS


def is_manual_only_destination(folder_path: str) -> bool:
    """Return whether a collection may be assigned but never suggested."""
    return _destination_group(folder_path) in MANUAL_ONLY_DESTINATION_GROUPS
