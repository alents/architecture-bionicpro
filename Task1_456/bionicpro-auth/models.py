from sqlalchemy import Column, String, DateTime
from sqlalchemy.sql import func
from database import Base


class UserProfile(Base):
    __tablename__ = "user_profiles"

    keycloak_id = Column(String, primary_key=True)
    email = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    birthday = Column(String, nullable=True)
    identity_provider = Column(String, nullable=True)  # "keycloak", "yandex" и т.д.
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())