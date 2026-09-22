"""Refresh multilingual character aliases used by the art resolver.

The generated JSON is committed so production sorting never depends on these
community/official sites being online. Run this script deliberately when game
rosters change, review the diff, and commit the result.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "src" / "character_aliases.json"
TIMEOUT_SECONDS = 30

GFL2_FOLDER = "Art/GAMES/GFL2"
ENDFIELD_FOLDER = "Art/GAMES/Arknights Endfield"
GENSHIN_FOLDER = "Art/GAMES/GENSHIN"
BA_FOLDER = "Art/GAMES/BA"

# The official English page currently renders several early names using its
# Japanese/TW assets. This canonical English roster fills that publication bug;
# the other languages still come directly from the official locale pages.
GFL2_ENGLISH_NAMES = """
Vepley Ullrid Daiyan Zhaohui Faye Qiuhua Belka Sakura Harpsy Lenna Suomi
Dushevnaya Centaureissi Mechty Vector Yoohee Springfield Jiangyu Florence Alva
Bathilde Basti Loreley Sextans Makiatto Qiongjiu Tololo Mosin-Nagant Papasha
Peritya Klukai Nikketa Lind Leva Robella Lewis Voymastina Lainie Phaetusa
Cheyanne Liushih OTs-14 Soppo Sabrina Peri Andoris Helen Krolik Cheeta Ksenia
Colphne Nagant Sharkry Lotta Littara Nemesis Groza M200
""".split()

# Simplified-Chinese names published by the mainland official site. The page's
# roster is client-rendered, so this reviewed list is kept beside the English
# fallback above instead of scraping unrelated prose from its metadata.
GFL2_SIMPLIFIED_NAMES = """
希丽雅 伊格蕾塔 阿斯缇亚 克莱妲 芙铃 维尔德 米蒂尔 索普 OTs-14 六分仪
刘莳 贝丝蒂 夏安 罗蕾莱 樱花 翡图萨 海伦 刘易斯 威玛西娜 埃芙 琳德
芙洛伦 莱妮 洛贝拉 莱娅 妮基塔 幼熙 秋桦 佩莉 春田 安朵丝 比悠卡 维克托
米什缇 可露凯 朝晖 杜莎妮 索米 乌尔丽德 玛绮朵 绛雨 佩里缇亚 莫辛纳甘 莱娜
琼玖 桑朵莱希 塞布丽娜 黛烟 托洛洛 纳美西丝 巴希达 哈卜茜 绯 波波沙 维普蕾 闪电
夏克里 克罗丽科 奇塔 纳甘 寇尔芙 莉塔拉 科谢尼娅 洛塔
""".split()


def _get(url: str) -> requests.Response:
    response = requests.get(url, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response


def _get_text(url: str) -> str:
    return _get(url).text


def _get_json(url: str) -> Any:
    return _get(url).json()


def _visible_text(value: str) -> str:
    return html.unescape(re.sub(r"<.*?>", "", value)).strip()


def gfl2_aliases() -> set[str]:
    aliases = {*GFL2_ENGLISH_NAMES, *GFL2_SIMPLIFIED_NAMES}
    for locale in ("en", "jp", "kr", "tw"):
        page = _get_text(f"https://gf2.haoplay.com/{locale}/roleinfo/")
        aliases.update(
            _visible_text(value)
            for value in re.findall(
                r'<div class="role-name">\s*(.*?)\s*</div>', page, re.S
            )
        )
    return aliases


def endfield_aliases() -> set[str]:
    aliases: set[str] = set()
    for locale in ("en-us", "ja-jp", "ko-kr", "zh-tw"):
        page = _get_text(f"https://endfield.gryphline.com/{locale}/operator")
        aliases.update(
            _visible_text(value)
            for value in re.findall(
                r"OperatorItem_nameText[^>]*>(.*?)</span>", page, re.S
            )
        )
    character_ids = _get_json(
        "https://endfield-assets.fffdan.com/table/CharacterTable"
    )
    simplified = _get_json(
        "https://endfield-assets.fffdan.com/i18n/dict/CN/table/CharacterTable/all"
    )
    for character_id in character_ids:
        character = _get_json(
            "https://endfield-assets.fffdan.com/table/CharacterTable/"
            f"{character_id}"
        )
        name_id = str(character["name"]["id"])
        localized_name = str(simplified.get(name_id, "")).strip()
        if localized_name:
            aliases.add(localized_name)
    return aliases


def genshin_aliases() -> set[str]:
    aliases: set[str] = set()
    for locale in ("en", "jp", "kr", "chs"):
        payload = _get_json(f"https://gi.yatta.moe/api/v2/{locale}/avatar")
        for character in payload["data"]["items"].values():
            aliases.add(str(character["name"]).strip())
            if locale == "en":
                aliases.add(str(character.get("route", "")).strip())
    return aliases


def blue_archive_aliases() -> set[str]:
    aliases: set[str] = set()
    for locale in ("en", "jp", "kr", "cn"):
        students = _get_json(
            f"https://schaledb.com/data/{locale}/students.min.json"
        )
        for student in students.values():
            for field in ("Name", "FamilyName", "PersonalName"):
                aliases.add(str(student.get(field, "")).strip())
            family = str(student.get("FamilyName", "")).strip()
            personal = str(student.get("PersonalName", "")).strip()
            if family and personal:
                aliases.add(f"{family} {personal}")
                aliases.add(f"{personal} {family}")
    return aliases


def _filter_and_sort_aliases(aliases: set[str]) -> list[str]:
    return sorted(
        {alias for alias in aliases if alias},
        key=lambda alias: (alias.casefold(), alias),
    )


def main() -> None:
    by_folder = {
        GFL2_FOLDER: _filter_and_sort_aliases(gfl2_aliases()),
        ENDFIELD_FOLDER: _filter_and_sort_aliases(endfield_aliases()),
        GENSHIN_FOLDER: _filter_and_sort_aliases(genshin_aliases()),
        BA_FOLDER: _filter_and_sort_aliases(blue_archive_aliases()),
    }
    OUTPUT.write_text(
        json.dumps(by_folder, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for folder, aliases in by_folder.items():
        print(f"{folder}: {len(aliases)} aliases")


if __name__ == "__main__":
    main()
