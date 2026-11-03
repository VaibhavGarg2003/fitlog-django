import time

import pytest

from apps.chat.tests.conftest import make_ticket, store_ticket
from apps.chat.tickets import TicketError, consume_ticket, verify_ticket


def test_valid_ticket_verifies():
    token, claims = make_ticket()
    ticket = verify_ticket(token)
    assert ticket.user_id == claims["sub"]
    assert ticket.jti == claims["jti"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"secret": "x" * 40},  # forged
        {"aud": "someone-else"},
        {"iss": "evil"},
        {"kid": "9"},  # unknown key
        {"iat": int(time.time()) - 600},  # expired long ago
        {"ttl": 3600},  # lifetime too long
        {"iat": int(time.time()) + 600},  # issued in the future
        {"user_id": "not-a-uuid"},
        {"jti": "short"},
    ],
)
def test_bad_tickets_are_refused(kwargs):
    token, _ = make_ticket(**kwargs)
    with pytest.raises(TicketError):
        verify_ticket(token)


@pytest.mark.parametrize("token", [None, "", 123, "a.b.c", "x" * 3000])
def test_garbage_is_refused(token):
    with pytest.raises(TicketError):
        verify_ticket(token)


def test_alg_none_is_refused():
    import jwt

    token = jwt.encode({"sub": "x"}, None, algorithm="none")
    with pytest.raises(TicketError):
        verify_ticket(token)


def test_previous_key_still_verifies_during_rotation(settings):
    old = "o" * 40
    settings.CHAT_WS_TICKET_PREVIOUS_SECRET = old
    settings.CHAT_WS_TICKET_PREVIOUS_KID = "0"
    token, _ = make_ticket(secret=old, kid="0")
    assert verify_ticket(token).jti


@pytest.mark.django_db
def test_ticket_is_single_use():
    token, claims = make_ticket()
    store_ticket(claims)
    ticket = verify_ticket(token)
    assert consume_ticket(ticket) is True
    assert consume_ticket(ticket) is False


@pytest.mark.django_db
def test_expired_or_unknown_rows_are_refused():
    token, claims = make_ticket()
    store_ticket(claims, expires_in=-1)
    assert consume_ticket(verify_ticket(token)) is False

    token2, _ = make_ticket()  # never stored (e.g. the user was deleted)
    assert consume_ticket(verify_ticket(token2)) is False


@pytest.mark.django_db
def test_ticket_bound_to_its_user():
    import uuid

    token, claims = make_ticket()
    store_ticket({**claims, "sub": str(uuid.uuid4())})  # row for someone else
    assert consume_ticket(verify_ticket(token)) is False
