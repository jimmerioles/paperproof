from __future__ import annotations

from paperproof.extract.rules import (
    _parse_late_fee,
    _parse_monthly_rent,
    _parse_notice,
    _parse_renewal,
    _parse_security_deposit,
    _parse_subletting,
    _parse_term,
)


def test_term_in_months() -> None:
    match = _parse_term("The term of this Lease is twenty-four (24) months, commencing soon.")
    assert match is not None
    assert match.value == 24


def test_term_in_years_converts_to_months() -> None:
    match = _parse_term("The term of this Lease is two (2) years.")
    assert match is not None
    assert match.value == 24


def test_notice_days_from_parenthetical() -> None:
    match = _parse_notice(
        "Either party may terminate by giving thirty (30) days' prior written notice."
    )
    assert match is not None
    assert match.value == 30


def test_notice_ignores_renewal_notice() -> None:
    match = _parse_notice(
        "Tenant may renew by delivering written notice sixty (60) days before expiration."
    )
    assert match is None


def test_subletting_prohibited() -> None:
    match = _parse_subletting("Tenant shall not sublet the Premises without consent.")
    assert match is not None
    assert match.value == "prohibited"


def test_subletting_with_consent() -> None:
    match = _parse_subletting("Tenant may sublet only with Landlord's prior written consent.")
    assert match is not None
    assert match.value == "allowed_with_consent"


def test_subletting_without_consent() -> None:
    match = _parse_subletting(
        "Tenant may sublet the Premises without Landlord's prior written consent."
    )
    assert match is not None
    assert match.value == "allowed"


def test_no_renewal_option_is_canonical() -> None:
    match = _parse_renewal("Tenant shall have no option to renew or extend the Term.")
    assert match is not None
    assert match.value == "No renewal option."


def test_money_fields() -> None:
    rent = _parse_monthly_rent("Tenant shall pay monthly rent of $2,400.00 on the first day.")
    deposit = _parse_security_deposit("Tenant shall pay a security deposit of $4,800.00.")
    late = _parse_late_fee("Tenant shall pay a late fee of $150.00 when rent is late.")
    assert rent is not None and rent.value == 2400
    assert deposit is not None and deposit.value == 4800
    assert late is not None and late.value == 150
