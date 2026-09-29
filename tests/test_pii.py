import pytest

from app.pii import scrub_text


def test_scrub_email() -> None:
    out = scrub_text("Email me at student@vinuni.edu.vn")
    assert "student@" not in out
    assert "REDACTED_EMAIL" in out


def test_scrub_email_with_plus_tag() -> None:
    out = scrub_text("Mail student+lab13@vinuni.edu.vn")
    assert out == "Mail [REDACTED_EMAIL]"


def test_scrub_common_vietnamese_phone_formats() -> None:
    phone_numbers = (
        "0901234567",
        "090 123 4567",
        "090.123.4567",
        "090-123-4567",
        "+84 90 123 4567",
    )

    for phone_number in phone_numbers:
        out = scrub_text(f"Contact: {phone_number}")
        assert phone_number not in out
        assert "REDACTED_PHONE_VN" in out


@pytest.mark.parametrize("cccd", ["012345678901", "079203001234"])
def test_scrub_cccd(cccd: str) -> None:
    assert scrub_text(f"CCCD {cccd} ok") == "CCCD [REDACTED_CCCD] ok"


@pytest.mark.parametrize(
    "card",
    ["4111 1111 1111 1111", "4111-1111-1111-1111", "4111111111111111", "0123 4567 8901 2345"],
)
def test_scrub_credit_card_as_one_token(card: str) -> None:
    assert scrub_text(f"card {card}.") == "card [REDACTED_CREDIT_CARD]."


def test_scrub_passport() -> None:
    assert scrub_text("Passport C1234567") == "Passport [REDACTED_PASSPORT]"


def test_scrub_keeps_non_pii_values() -> None:
    text = "req-1a2b3c4d latency 583ms, 10 docs, claude-sonnet-4-5, cost 0.002508"
    assert scrub_text(text) == text
