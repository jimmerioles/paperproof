from __future__ import annotations

from paperproof.extract.verify import PageRecord, verify_quote
from paperproof.ingest.pdf import Word


def make_page(lines: list[str], y_start: float = 100.0) -> PageRecord:
    words: list[Word] = []
    y = y_start
    for line in lines:
        x = 72.0
        for token in line.split():
            words.append(Word(token, x=x, y=y, w=40.0, h=10.0))
            x += 44.0
        y += 16.0
    return PageRecord(pdf_page=1, printed_label="1", width=612, height=792, words=words)


def test_exact_quote_with_curly_punctuation() -> None:
    page = make_page(["Tenant may sublet only with Landlord's prior written consent."])
    result = verify_quote(
        [page], "Tenant may sublet only with Landlord\u2019s prior written consent."
    )
    assert result is not None
    assert result.method == "exact"
    assert result.pdf_page == 1
    assert result.boxes


def test_quote_across_two_lines_gets_two_boxes() -> None:
    page = make_page(
        [
            "Tenant may sublet the Premises only with",
            "Landlord's prior written consent.",
        ]
    )
    result = verify_quote(
        [page],
        "Tenant may sublet the Premises only with Landlord's prior written consent",
    )
    assert result is not None
    assert result.method == "exact"
    assert len(result.boxes) == 2


def test_fuzzy_quote_tolerates_one_bad_word() -> None:
    page = make_page(["Tenant may sublet the Premises without consent."])
    result = verify_quote([page], "Tenant may sublet the Premise without consent.")
    assert result is not None
    assert result.method == "fuzzy"
    assert 0.8 <= result.score <= 1.0


def test_unfindable_quote_returns_none() -> None:
    page = make_page(["The security deposit is four thousand dollars."])
    assert verify_quote([page], "The tenant may keep a pet.") is None


def test_hint_page_is_preferred() -> None:
    first = PageRecord(1, "1", 612, 792, make_page(["Notice is thirty days."]).words)
    second = PageRecord(2, "2", 612, 792, make_page(["Notice is thirty days."]).words)
    result = verify_quote([first, second], "Notice is thirty days.", hint_page=2)
    assert result is not None
    assert result.pdf_page == 2
