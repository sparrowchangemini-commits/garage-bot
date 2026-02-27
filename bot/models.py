from datetime import date, datetime

from sqlalchemy import Boolean, Column, Date, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .db import Base


class User(Base):
    __tablename__ = "users"

    tg_id = Column(Integer, primary_key=True, index=True)
    username = Column(String(255), index=True, nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    owner_handle = Column(String(255), index=True, nullable=True)

    renter_bookings = relationship("Booking", back_populates="renter", foreign_keys="Booking.renter_user_id")
    owner_bookings = relationship("Booking", back_populates="owner", foreign_keys="Booking.owner_user_id")


class Item(Base):
    __tablename__ = "items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sheet_row = Column(Integer, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    price_raw = Column(String(255), nullable=False)
    price_eur = Column(Integer, nullable=True)
    period_unit = Column(String(50), nullable=True)
    owner_handle = Column(String(255), index=True, nullable=False)
    area = Column(String(255), nullable=True)
    type = Column(String(100), nullable=True)
    comment = Column(Text, nullable=True)
    deposit_required = Column(Boolean, default=False, nullable=False)
    photo_url = Column(String(512), nullable=True)

    bookings = relationship("Booking", back_populates="item")


from enum import Enum as PyEnum


class BookingState(str, PyEnum):
    pending_owner_confirm = "pending_owner_confirm"
    confirmed_unpaid = "confirmed_unpaid"
    paid_confirmed = "paid_confirmed"
    canceled_by_owner = "canceled_by_owner"
    canceled_by_renter = "canceled_by_renter"
    canceled_unpaid_timeout = "canceled_unpaid_timeout"


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False, index=True)
    renter_user_id = Column(Integer, ForeignKey("users.tg_id"), nullable=False, index=True)
    owner_user_id = Column(Integer, ForeignKey("users.tg_id"), nullable=False, index=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    state = Column(Enum(BookingState), nullable=False, index=True)
    paid_confirmed_at = Column(DateTime, nullable=True)
    refund_confirmed_at = Column(DateTime, nullable=True)
    last_refund_reminder_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    canceled_reason = Column(Text, nullable=True)

    item = relationship("Item", back_populates="bookings")
    renter = relationship("User", back_populates="renter_bookings", foreign_keys=[renter_user_id])
    owner = relationship("User", back_populates="owner_bookings", foreign_keys=[owner_user_id])
    notifications = relationship("Notification", back_populates="booking")


class NotificationType(str, PyEnum):
    minus_24h = "minus_24h"
    minus_12h = "minus_12h"
    minus_2h = "minus_2h"
    start_check = "start_check"


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False, index=True)
    type = Column(Enum(NotificationType), nullable=False)
    scheduled_for = Column(DateTime, nullable=False)
    sent = Column(Boolean, default=False, nullable=False)
    sent_at = Column(DateTime, nullable=True)

    booking = relationship("Booking", back_populates="notifications")

