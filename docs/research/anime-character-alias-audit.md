# Anime character alias audit

Research date: 2026-09-25

## Conclusion

The anime import cannot treat the existing Obsidian character-note filenames as a complete roster or as canonical names. The vault currently has 79 character notes across 21 anime, but several series have only one member of an ensemble, some filenames are Chinese translations rather than Japanese names, and a few filenames are incorrect or non-canonical.

Use this source priority for generated aliases:

1. Japanese name and roster membership from the anime/franchise's official Japanese site.
2. Latin spelling from the official English-language publisher when one exists.
3. Chinese spelling only from an official Chinese licensee/publisher when available; otherwise retain the vault spelling but label it `vault-derived`, not `official`.
4. A deterministic Hepburn transliteration may be added for matching, but must be labeled `inferred`, not `official`.

## High-priority corrections

### Non Non Biyori

The vault has only `越谷夏海.md`. The official anime character page identifies four central girls—宮内れんげ, 一条蛍, 越谷夏海, and 越谷小鞠—and the first-episode synopsis explicitly presents those four together. Therefore all four belong in the alias registry even though three have no vault note. ([TV Tokyo official character page](https://www.tv-tokyo.co.jp/anime/nonnon_ns/chara/), [official episode 1 synopsis](https://nonnontv.com/tvanime/story/season1/s01))

| Canonical Japanese | Latin alias | Chinese alias | Provenance |
|---|---|---|---|
| 宮内れんげ | Renge Miyauchi; Miyauchi Renge | 宫内莲华 | Japanese official; Latin is inferred Hepburn/order variants; Chinese is common Simplified Chinese, not verified here against a first-party licensee |
| 一条蛍 | Hotaru Ichijo; Ichijo Hotaru | 一条萤 | Japanese official; Latin inferred; Chinese unverified |
| 越谷夏海 | Natsumi Koshigaya; Koshigaya Natsumi | 越谷夏海 | Japanese official; Latin inferred; Chinese is script-identical |
| 越谷小鞠 | Komari Koshigaya; Koshigaya Komari | 越谷小鞠 | Japanese official; Latin inferred; Chinese is script-identical |

### Oregairu

The four vault notes correspond to the four leads listed by BS-TBS, but the alias data is uneven: Hachiman has no Latin alias, and the Yukino filename is misspelled `雪ノ下雪の`. The official spelling is `雪ノ下雪乃`. ([BS-TBS official program page](https://bs.tbs.co.jp/anime/oregairu/), [TBS official first-season cast](https://www.tbs.co.jp/anime/oregairu/1st/staffcast/))

Yen Press, the official English publisher, establishes `Hachiman Hikigaya`, `Yukino Yukinoshita`, and `Yui Yuigahama`; it also uses `Iroha Isshiki`. ([official English series page](https://yenpress.com/series/my-youth-romantic-comedy-is-wrong-as-i-expected-comic-manga), [official English volume 11](https://yenpress.com/titles/9781975333638-my-youth-romantic-comedy-is-wrong-as-i-expected-vol-11-light-novel))

| Canonical Japanese | Official English | Reverse-order matching alias | Chinese vault alias/status |
|---|---|---|---|
| 比企谷八幡 | Hachiman Hikigaya | Hikigaya Hachiman | 比企谷八幡 (script-identical) |
| 雪ノ下雪乃 | Yukino Yukinoshita | Yukinoshita Yukino | 雪之下雪乃 (vault-derived) |
| 由比ヶ浜結衣 | Yui Yuigahama | Yuigahama Yui | 由比滨结衣 (vault-derived) |
| 一色いろは | Iroha Isshiki | Isshiki Iroha | 一色伊吕波 (vault-derived) |

### Date A Live

All 13 current filenames are Chinese-only or Chinese-influenced. The official Japanese season-five site supplies the canonical Japanese roster. Two vault filenames are materially wrong for routing purposes: `冰芽川四糸乃` should include the official name `四糸乃`, and `镜野七罪` should include the official name `七罪`; those surnames do not appear on the official character roster. The vault also omits protagonist `五河士道`. ([official season-five site and cast](https://date-a-live5th-anime.com/), [official current character roster](https://date-a-livef-anime.com/))

Yen Press's licensed English releases establish the name forms used below for Kotori, Kurumi, Mukuro, Nia, Tobiichi, Natsumi, Miku, and Yamai through their volume titles and descriptions. ([Yen Press official series/volume listing](https://yenpress.com/series/date-a-live-light-novel), [volume 4: Kotori Itsuka](https://yenpress.com/titles/9781975319984-date-a-live-vol-4-light-novel), [licensed Kurumi spelling](https://yenpress.com/titles/9798855410600-casebook-of-kurumi-tokisaki-magic-detective-light-novel))

| Canonical Japanese | Latin/English alias | Existing Chinese filename | Status |
|---|---|---|---|
| 五河士道 | Shido Itsuka; Itsuka Shido | — | Missing note and alias; Latin spelling supported by Yen Press prose |
| 夜刀神十香 | Tohka Yatogami; Yatogami Tohka | 夜刀神十香 | Latin form follows licensed English naming convention; `Tohka` should be preferred over bare transliteration `Toka` |
| 鳶一折紙 | Origami Tobiichi; Tobiichi Origami | 鸢一折纸 | `Tobiichi` is licensed English |
| 五河琴里 | Kotori Itsuka; Itsuka Kotori | 五河琴里 | Licensed English |
| 四糸乃 | Yoshino | 冰芽川四糸乃 | Official Japanese is mononymous; keep the Chinese filename only as a search alias |
| 時崎狂三 | Kurumi Tokisaki; Tokisaki Kurumi | 时崎狂三 | Licensed English |
| 八舞耶倶矢 | Kaguya Yamai; Yamai Kaguya | 八舞耶俱矢 | `Yamai` is licensed English; given-name romanization inferred |
| 八舞夕弦 | Yuzuru Yamai; Yamai Yuzuru | 八舞夕弦 | `Yamai` is licensed English; given-name romanization inferred |
| 誘宵美九 | Miku Izayoi; Izayoi Miku | 诱宵美九 | `Miku` is licensed English; surname transliteration inferred |
| 七罪 | Natsumi | 镜野七罪 | Licensed English volume title and official Japanese roster are mononymous |
| 本条二亜 | Nia Honjo; Honjo Nia | 本条二亚 | `Nia` is licensed English; surname transliteration inferred |
| 星宮六喰 | Mukuro Hoshimiya; Hoshimiya Mukuro | 星宫六喰 | `Mukuro` is licensed English; surname transliteration inferred |
| 崇宮澪 | Mio Takamiya; Takamiya Mio | 崇宫澪 | Latin inferred from Japanese |
| エレン・ミラ・メイザース | Ellen Mira Mathers | 艾伦·米拉·马瑟斯 | Japanese/Latin form requires a separate official character-page check; the season-five lead roster does not include her |

## Whole-vault roster audit

“Missing” below means absent from the vault's `characters/` notes despite appearing among the principal ensemble on an official anime page. It is intentionally conservative: it does not attempt to import every supporting cast member.

| Anime folder | Vault notes | Audit result |
|---|---:|---|
| Angel Beats | 4 | Fix `芳岡ユイ`: the official site calls the character simply `ユイ`. Current core selection otherwise covers ゆり, 天使/立華かなで, 音無, and ユイ. ([official character page](https://www.angelbeats.jp/chara/index.html)) |
| Charlotte | 1 | Incomplete. Add at least 乙坂有宇, 高城丈士朗, 西森柚咲, 美砂, and 乙坂歩未 beside existing 友利奈緒. ([official character page](https://charlotte-anime.jp/character/)) |
| Date a Live | 13 | Names need the corrections above; add 五河士道. |
| GIRLS und PANZER | 11 | The five Anglerfish Team leads—西住みほ, 武部沙織, 五十鈴華, 秋山優花里, 冷泉麻子—are present. |
| K-ON | 4 | Incomplete. Add 田井中律 and 琴吹紬; the official principal band is 唯, 澪, 律, 紬, 梓. ([Kyoto Animation official work page](https://www.kyotoanimation.co.jp/works/k-onMovie/)) |
| lucky star | 4 | Core four are present; multilingual aliases still need licensed-English verification. |
| お兄ちゃんはおしまい！ | 2 | The official character page presents six principals. Keep Mahiro and Mihari and supplement 穂月もみじ, 穂月かえで, 桜花あさひ, and 室崎みよ. ([official character page](https://onimai.jp/character/)) |
| この素晴らしい世界に祝福を！ | 3 | Incomplete. Add カズマ to アクア, めぐみん, and ダクネス. ([official character page](https://konosuba.com/3rd/character/)) |
| さくら荘のペットな彼女 | 1 | Incomplete. Add at least 神田空太, 青山七海, 上井草美咲, 三鷹仁, and 赤坂龍之介. ([official cast](https://sakurasou.tv/staff.html)) |
| とらドラ！ | 1 | Clearly incomplete (only 逢坂大河); requires an official-roster pass before import expansion. |
| のんのんびより | 1 | Incomplete; add the three characters detailed above. |
| ぼっち・ざ・ろっく！ | 4 | Complete for the four-member 結束バンド core. ([official cast](https://bocchi.rocks/tv/caststaff/)) |
| やはり俺の青春ラブコメはまちがっている。 | 4 | Core four present; fix and expand aliases as above. |
| ゆるキャン△ | 8 | Main five and several principal supporting characters are present; normalize filenames to official Japanese while retaining Latin filenames as aliases. ([official character page](https://yurucamp.jp/first/character/), [official film cast](https://yurucamp.jp/cinema/staffcast/)) |
| りゅうおうのおしごと！ | 1 | Incomplete. Supplement the five top-billed principals 九頭竜八一, 雛鶴あい, 夜叉神天衣, 空銀子, and 清滝桂香. ([official cast](https://www.ryuoh-anime.com/staff/index.html)) |
| ハヤテのごとく！ | 2 | Incomplete: supplement title protagonist 綾崎ハヤテ and マリア beside existing 三千院ナギ and 桂ヒナギク. |
| 五等分の花嫁 | 5 | The five sisters are present, but protagonist 上杉風太郎 is absent if “all main characters” is literal. |
| 冴えない彼女の育てかた | 1 | Incomplete: supplement 安芸倫也, 加藤恵, 澤村・スペンサー・英梨々, and 氷堂美智留 beside existing 霞ヶ丘詩羽. |
| 時々ボソッとロシア語でデレる隣のアーリャさん | 5 | Likely incomplete: protagonist 久世政近 is absent; current Latin filenames should gain official Japanese aliases. |
| 灼眼のシャナ | 2 | Incomplete if the lead pair is intended: 坂井悠二 is absent. |
| 阿波連さんははかれない | 1 | Incomplete: add the other official lead as `ライドウ` / `RAIDO`; the official site does not supply a personal name. ([official character page](https://aharen-pr.com/1st/character/)) |
| 魔女の旅々 | 1 | Elaina/イレイナ is the sole title protagonist; add both Japanese and Latin aliases if not already present. |

## Import implications

- Do not infer roster completeness from the existence of a `characters/` folder.
- Store provenance per alias (`official-ja`, `official-en`, `official-zh`, `vault`, `inferred`) or keep a checked-in supplemental data file whose comments/sources provide the same audit trail.
- Preserve both Western and Japanese name order for Latin tags because booru/WD14 labels commonly use `family_given` while licensed prose uses `Given Family`.
- Correct canonical names without deleting old vault spellings; erroneous or translated filenames can still be useful low-priority matching aliases.
- The generic `Art/ANIME` destination currently combines unrelated anime. A name-to-series supplement should still route to the actual collection only when that collection exists; otherwise it risks replacing one ambiguity with another.
