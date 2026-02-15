from sqlalchemy import Column, String, DateTime, Integer
from sqlalchemy.sql import func
from database import Base


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id = Column(Integer, primary_key=True, autoincrement=True)
    subject_id = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    birthday = Column(String, nullable=True)
    identity_provider = Column(String, nullable=True)  # "keycloak", "yandex" и т.д.
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())