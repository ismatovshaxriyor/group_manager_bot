import datetime
from peewee import (
    SqliteDatabase,
    Model,
    BigIntegerField,
    CharField,
    IntegerField,
    DateTimeField,
    ForeignKeyField,
    BooleanField,
)

db = SqliteDatabase("bot.db")


class BaseModel(Model):
    class Meta:
        database = db


class User(BaseModel):
    telegram_id = BigIntegerField(unique=True)
    first_name = CharField()
    last_name = CharField()
    phone = CharField()
    username = CharField(null=True)
    created_at = DateTimeField(default=datetime.datetime.now)


class Card(BaseModel):
    """Payment card info — managed by admin via /admin."""
    card_number = CharField()
    card_holder = CharField()
    is_active = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.datetime.now)


class Channel(BaseModel):
    """Channels/groups users join after payment — managed by admin via /admin."""
    chat_id = BigIntegerField()
    title = CharField(default="")
    is_active = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.datetime.now)


class Payment(BaseModel):
    user = ForeignKeyField(User, backref="payments")
    amount = IntegerField()
    receipt_file_id = CharField()
    status = CharField(default="pending")  # pending / approved / rejected
    approved_by = BigIntegerField(null=True)
    created_at = DateTimeField(default=datetime.datetime.now)
    approved_at = DateTimeField(null=True)


class Subscription(BaseModel):
    user = ForeignKeyField(User, backref="subscriptions")
    payment = ForeignKeyField(Payment, backref="subscription")
    start_date = DateTimeField(default=datetime.datetime.now)
    end_date = DateTimeField()
    is_active = BooleanField(default=True)
    warning_sent = BooleanField(default=False)


def create_tables():
    with db:
        db.create_tables([User, Card, Channel, Payment, Subscription])
