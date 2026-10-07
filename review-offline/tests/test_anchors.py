from review_offline.anchors import anchor_hash, line_hash, side_lines

FILE = {
    "hunks": [
        {
            "lines": [
                {"t": "ctx", "o": 1, "n": 1, "text": "a"},
                {"t": "del", "o": 2, "n": None, "text": "b"},
                {"t": "add", "o": None, "n": 2, "text": "c"},
            ]
        }
    ]
}


def test_side_lines_old_and_new():
    assert side_lines(FILE, "old", 1, 2) == ["a", "b"]
    assert side_lines(FILE, "new", 1, 2) == ["a", "c"]


def test_missing_line_returns_none():
    assert side_lines(FILE, "new", 2, 3) is None
    assert anchor_hash(FILE, "old", 3, 3) is None


def test_hash_is_stable_12_hex():
    h = line_hash(["a", "b"])
    assert len(h) == 12 and h == anchor_hash(FILE, "old", 1, 2)
