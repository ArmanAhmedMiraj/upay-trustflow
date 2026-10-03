import pytest
from sqlalchemy.exc import IntegrityError

from models import Transaction, User
from wallet_helpers import make_session


def test_create_users_and_a_transaction():
    db = make_session()
    rahim = User(phone="01711000001", name="Rahim", pin_hash="x", balance=10000)
    karim = User(phone="01711000002", name="Karim", pin_hash="x")
    db.add_all([rahim, karim])
    db.commit()

    db.add(Transaction(kind="send_money", sender_id=rahim.id, receiver_id=karim.id, amount=500))
    db.commit()

    saved = db.query(Transaction).one()
    assert saved.amount == 500
    assert saved.status == "completed"
    assert saved.sender_id == rahim.id


def test_phone_number_must_be_unique():
    db = make_session()
    db.add(User(phone="01711000001", name="A", pin_hash="x"))
    db.commit()
    db.add(User(phone="01711000001", name="B", pin_hash="x"))
    with pytest.raises(IntegrityError):
        db.commit()
