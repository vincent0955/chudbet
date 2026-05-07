from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.models import User
from app.db.session import get_db
from app.services.auth import resolve_session_user

SESSION_COOKIE_NAME = "chudbet_session"


def session_cookie_token(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE_NAME)


def get_current_user_optional(
    request: Request, db: Session = Depends(get_db)
) -> User | None:
    return resolve_session_user(db, session_cookie_token(request))


def get_current_user(
    user: User | None = Depends(get_current_user_optional),
) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user
