"""User-confirmed resolver corrections and reusable visual aliases."""

import re
import unicodedata
from typing import Any

from src.modality import bookmark_modality
from src.wd14_tagger import semantic_tag_keys


BOOKMARK_ROUTES: dict[int, str] = {
    1860416132: "Art/TOUHOU",
    1861076432: "Art/GAMES/BA",
    1860716167: "Art/GAMES/BA",
    1860392169: "Art/ANIME/MAJONOTABITABI",
    1860292294: "Art/MIKU",
    1860292290: "Art/ANIME/MAJONOTABITABI",
    1860037727: "Art/GAMES/BA",
    1860037717: "Art/MIKU",
    1859637128: "Art/GAMES/FGO",
    1859600128: "Art/MIKU",
    1859600122: "Art/ANIME/lucky star",
    1860052154: "Art/GAMES/BA",
    1859600099: "Art/VTUBERS",
    1859254203: "Art/GAMES/BA",
    1859290755: "Art/GAMES/BA",
    1859254200: "Art/GAMES/BA",
    1859152957: "Art/GAMES/GFL2",
    1859138295: "Art/TOUHOU",
    1859152949: "Art/GAMES/BA",
    1859160939: "Art/GAMES/BA",
    1859454297: "Art/GAMES/BA",
    1859100626: "Art/GAMES/GFL2",
    1859102703: "Art/NEUROVERSE/EVIL",
    1858587910: "Art/GAMES/BA",
    1859152945: "Art/GAMES/BA",
    1859191393: "Art/GAMES/GALGAME",
    1859152931: "Art/VTUBERS",
    1858587892: "Art/MISCE",
    1858587884: "Art/MIKU",
    1859152928: "Art/IDOL@MASTER",
    1859104912: "Art/GAMES/BA",
    1858601441: "Art/GAMES/FGO",
    1859117686: "Art/VTUBERS",
}
TAG_ROUTES: dict[str, str] = {
    "hatsune_miku": "Art/MIKU",
    "hakurei_reimu": "Art/TOUHOU",
    "komeiji_satori": "Art/TOUHOU",
    "majo_no_tabitabi": "Art/ANIME/MAJONOTABITABI",
    "elaina_(majo_no_tabitabi)": "Art/ANIME/MAJONOTABITABI",
    "izumi_konata": "Art/ANIME/lucky star",
    "lucky_star": "Art/ANIME/lucky star",
    "blue_archive": "Art/GAMES/BA",
    "mari_(blue_archive)": "Art/GAMES/BA",
    "mutsuki_(blue_archive)": "Art/GAMES/BA",
    "fate": "Art/GAMES/FGO",
    "fate/extra": "Art/GAMES/FGO",
    "nero_claudius_(fate)": "Art/GAMES/FGO",
    "saber_(fate)": "Art/GAMES/FGO",
    "artoria_pendragon_(fate)": "Art/GAMES/FGO",
    "groza": "Art/GAMES/GFL2",
    "groza-14": "Art/GAMES/GFL2",
    "ots-14_(girls'_frontline)": "Art/GAMES/GFL2",
    "klukai": "Art/GAMES/GFL2",
    "evil_neuro": "Art/NEUROVERSE/EVIL",
    "evilneuro": "Art/NEUROVERSE/EVIL",
    "neuro_evil": "Art/NEUROVERSE/EVIL",
    "hoshimachi_suisei": "Art/VTUBERS",
    "hanami_saki": "Art/IDOL@MASTER",
    "furukawa_nagisa": "Art/GAMES/GALGAME",
    "hurukaga_nagisa": "Art/GAMES/GALGAME",
}
TEXT_ROUTES: dict[str, str] = {
    "初音ミク": "Art/MIKU",
    "ほしまちぎゃらりー": "Art/VTUBERS",
    "星街すいせい": "Art/VTUBERS",
    "すいちゃん": "Art/VTUBERS",
    "hoshimachi suisei": "Art/VTUBERS",
    "clannad": "Art/GAMES/GALGAME",
    "花海咲季": "Art/IDOL@MASTER",
    "アコ": "Art/GAMES/BA",
    "コユキ": "Art/GAMES/BA",
    "ユウカ": "Art/GAMES/BA",
    "ムツキ": "Art/GAMES/BA",
    "miyako": "Art/GAMES/BA",
    "이부키": "Art/GAMES/BA",
    "イレイナ": "Art/ANIME/MAJONOTABITABI",
    "いれいな": "Art/ANIME/MAJONOTABITABI",
    "らきすた": "Art/ANIME/lucky star",
    "こなた": "Art/ANIME/lucky star",
    "capoo": "Art/MISCE",
    "カプー": "Art/MISCE",
    "咖波": "Art/MISCE",
    "evil neuro": "Art/NEUROVERSE/EVIL",
    "groza-14": "Art/GAMES/GFL2",
    "klukai": "Art/GAMES/GFL2",
    "furukawa nagisa": "Art/GAMES/GALGAME",
    "古河渚": "Art/GAMES/GALGAME",
}
SOURCE_ROUTES: dict[str, str] = {
    "x.com/bugcat_capoo_tw/": "Art/MISCE",
    "twitter.com/bugcat_capoo_tw/": "Art/MISCE",
}


def _contains_text_alias(text: str, alias: str) -> bool:
    if not alias.isascii():
        return alias in text
    return re.search(
        rf"(?<![\w]){re.escape(alias)}(?![\w])",
        text,
    ) is not None


def calibrated_bookmark_folder(
    bookmark: dict[str, Any],
) -> tuple[str, str] | None:
    """Return an exact user-confirmed bookmark destination."""
    raw_bookmark_id = bookmark.get("_id")
    if raw_bookmark_id is not None:
        try:
            bookmark_id = int(raw_bookmark_id)
        except (TypeError, ValueError):
            bookmark_id = None
        if bookmark_id is not None:
            folder = BOOKMARK_ROUTES.get(bookmark_id)
            if folder is not None:
                return folder, f"user_calibration:{bookmark_id}"
    return None


def calibrated_content_folder(
    bookmark: dict[str, Any],
) -> tuple[str, str] | None:
    """Generalize confirmed visual and textual aliases to new art."""
    if bookmark_modality(bookmark) == "art":
        semantic_tags = {
            semantic_tag
            for raw_tag in bookmark.get("tags", [])
            for semantic_tag in semantic_tag_keys(
                str(raw_tag).removeprefix("ai:wdtag-")
            )
        }
        for tag, target in TAG_ROUTES.items():
            if tag in semantic_tags:
                return target, f"calibrated_tag:{tag}"
        searchable_text = unicodedata.normalize(
            "NFKC",
            "\n".join(
                str(bookmark.get(field, "") or "")
                for field in ("title", "excerpt", "note")
            ),
        ).casefold()
        for alias, target in TEXT_ROUTES.items():
            normalized_alias = unicodedata.normalize("NFKC", alias).casefold()
            if _contains_text_alias(searchable_text, normalized_alias):
                return target, f"calibrated_text:{normalized_alias}"
        source = str(bookmark.get("link", "") or "").casefold()
        for source_fragment, target in SOURCE_ROUTES.items():
            if source_fragment in source:
                return target, f"calibrated_source:{source_fragment}"
    return None
