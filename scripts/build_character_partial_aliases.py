"""Build an audited partial-name registry from the committed full-name registry."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
import re
import unicodedata


DEFAULT_SOURCE = Path(__file__).parents[1] / "src" / "character_aliases.json"
DEFAULT_OUTPUT = (
    Path(__file__).parents[1] / "src" / "character_partial_aliases.json"
)

# These tokens occur inside real character names but are too likely to appear as
# ordinary prose, franchise terminology, titles, or honorifics. The generated
# registry is committed so additions remain reviewable.
UNSAFE_PARTIALS = {
    "acute", "admire", "almond", "amazon", "arabian", "bamboo", "barb",
    "bitter", "black", "blast", "bloom", "bright", "bubble", "cafe",
    "casino", "chan", "china", "city", "condor", "creek", "cross", "crown",
    "dance", "daring", "desire", "diamond", "digital", "dream", "drive",
    "earth", "electro", "evil", "falcon", "fellow", "festa", "fine", "flame",
    "flash", "flight", "flower", "forever", "genesis", "girl", "gold", "gran",
    "grand", "grass", "groove", "halo", "happy", "hare", "heart", "hello",
    "hydro", "journey", "jungle", "king", "kingdom", "knowledge", "last",
    "lemon", "light", "lights", "lite", "little", "love", "loves", "lucky",
    "march", "marvelous", "medicine", "meek", "melancholy", "memory", "mine",
    "miracle", "motion", "nature", "neuro", "nice", "north", "only", "pearl",
    "pegasus", "pocket", "princess", "pyro", "reason", "rice", "road", "rose",
    "sama", "seeking", "ship", "shogun", "shower", "shuttle", "silence",
    "silver", "smart", "sounds", "special", "speed", "stay", "still", "sugar",
    "sunday", "super", "swan", "sweep", "ticket", "traveler", "turbo", "twin",
    "universe", "variation", "vista", "week", "white", "window", "windy",
    "winning", "wolf", "wonder", "young",
}

MANUAL_PARTIALS: dict[str, tuple[str, ...]] = {
    "sanae": ("Art/TOUHOU",),
    "咲季": ("Art/IDOL@MASTER",),
    "手毬": ("Art/IDOL@MASTER",),
    "ことね": ("Art/IDOL@MASTER",),
    "麻央": ("Art/IDOL@MASTER",),
    "リーリヤ": ("Art/IDOL@MASTER",),
    "千奈": ("Art/IDOL@MASTER",),
    "清夏": ("Art/IDOL@MASTER",),
    "莉波": ("Art/IDOL@MASTER",),
    "佑芽": ("Art/IDOL@MASTER",),
    "美鈴": ("Art/IDOL@MASTER", "Art/TOUHOU"),
    "星南": ("Art/IDOL@MASTER",),
}

_LATIN_NAME_PART = re.compile(r"^[A-Za-z][A-Za-z'’ʼ-]*$")


def build_partial_registry(
    full_registry: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Return destination -> safe partial aliases, retaining ambiguities."""
    destinations_by_alias: dict[str, set[str]] = defaultdict(set)
    for destination, aliases in full_registry.items():
        for alias in aliases:
            parts = alias.split()
            if len(parts) < 2:
                continue
            for part in parts:
                normalized = unicodedata.normalize("NFKC", part).casefold()
                if _LATIN_NAME_PART.fullmatch(part):
                    if len(normalized) < 4 or normalized in UNSAFE_PARTIALS:
                        continue
                elif part.isascii() or len(normalized) < 2:
                    continue
                destinations_by_alias[normalized].add(destination)

    for alias, destinations in MANUAL_PARTIALS.items():
        destinations_by_alias[alias].update(destinations)

    aliases_by_destination: dict[str, list[str]] = defaultdict(list)
    for alias, destinations in destinations_by_alias.items():
        for destination in destinations:
            aliases_by_destination[destination].append(alias)
    return {
        destination: sorted(aliases, key=lambda alias: (alias.casefold(), alias))
        for destination, aliases in sorted(aliases_by_destination.items())
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    full_registry: dict[str, list[str]] = json.loads(
        args.source.read_text(encoding="utf-8")
    )
    partial_registry = build_partial_registry(full_registry)
    args.output.write_text(
        json.dumps(partial_registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
