from src.modality import bookmark_modality


def test_pixiv_link_with_image_media_is_visual_art():
    bookmark = {
        "type": "link",
        "domain": "pixiv.net",
        "link": "https://www.pixiv.net/en/artworks/149957672",
        "cover": "https://embed.pixiv.net/artwork.php?illust_id=149957672",
        "media": [
            {
                "type": "image",
                "link": "https://i.pximg.net/img-master/example.jpg",
            }
        ],
    }

    assert bookmark_modality(bookmark) == "art"


def test_generic_link_with_decorative_image_is_not_assumed_to_be_art():
    bookmark = {
        "type": "link",
        "domain": "example.com",
        "link": "https://example.com/article",
        "cover": "https://example.com/social-card.jpg",
        "media": [{"type": "image", "link": "https://example.com/hero.jpg"}],
    }

    assert bookmark_modality(bookmark) is None


def test_pixiv_is_detected_from_link_when_domain_is_missing():
    assert bookmark_modality(
        {
            "type": "link",
            "link": "https://www.pixiv.net/en/artworks/149957672",
            "media": [{"type": "image", "link": "https://i.pximg.net/a.jpg"}],
        }
    ) == "art"


def test_pixiv_subdomain_with_cover_only_is_visual_art():
    assert bookmark_modality(
        {
            "type": "link",
            "domain": "touch.pixiv.net",
            "link": "https://touch.pixiv.net/artworks/1",
            "cover": "https://i.pximg.net/a.jpg",
        }
    ) == "art"


def test_malformed_media_entries_do_not_break_modality_detection():
    assert bookmark_modality(
        {"type": "link", "domain": "example.com", "media": [None, "image"]}
    ) is None
