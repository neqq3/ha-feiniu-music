"""Plain and line-synchronized lyrics without MA dependencies."""

from custom_components.feiniu_music.lyrics import parse_lyrics


def test_plain_and_empty_lyrics():
    assert parse_lyrics({"list": []}) == {"text": "", "synced_lines": []}
    assert parse_lyrics({"list": [{"content": "Hello\nWorld"}]}) == {
        "text": "Hello\nWorld",
        "synced_lines": [],
    }


def test_preferred_synchronized_lyrics_and_native_offset():
    result = parse_lyrics(
        {
            "preferred": "chosen",
            "list": [
                {"content": "Other"},
                {
                    "guid": "chosen",
                    "offset": 500,
                    "content": "[00:02.00]Second\n[00:01.00][00:03.00]Repeated",
                },
            ],
        }
    )
    assert result["synced_lines"] == [
        {"time_ms": 500, "text": "Repeated"},
        {"time_ms": 1500, "text": "Second"},
        {"time_ms": 2500, "text": "Repeated"},
    ]
