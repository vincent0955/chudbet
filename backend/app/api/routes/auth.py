from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.api.auth import SESSION_COOKIE_NAME, get_current_user
from app.api.schemas import AuthLoginBody, AuthMeRead, AuthSignupBody, UserRead
from app.db.models import User
from app.db.session import get_db
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=60 * 60 * 24 * 30,
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")


def _user_agent(req: Request) -> str | None:
    return req.headers.get("user-agent")


@router.post("/signup", response_model=AuthMeRead, status_code=201)
def post_signup(body: AuthSignupBody, response: Response, request: Request, db: Session = Depends(get_db)) -> AuthMeRead:
    password = body.password.strip()
    email = body.email.strip()
    username = body.username.strip()
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="password must be at least 8 characters")
    if "@" not in email:
        raise HTTPException(status_code=400, detail="invalid email")
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="username must be at least 3 characters")
    try:
        user, account, token = auth_service.signup_user(
            db, email=email, username=username, password=password, user_agent=_user_agent(request)
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    _set_auth_cookie(response, token)
    return AuthMeRead(
        user=UserRead.model_validate(user),
        account_id=account.id,
        balance_cents=account.balance_cents,
    )


@router.post("/login", response_model=AuthMeRead)
def post_login(body: AuthLoginBody, response: Response, request: Request, db: Session = Depends(get_db)) -> AuthMeRead:
    try:
        user, account, token = auth_service.login_user(
            db, email=body.email, password=body.password, user_agent=_user_agent(request)
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    _set_auth_cookie(response, token)
    return AuthMeRead(
        user=UserRead.model_validate(user),
        account_id=account.id,
        balance_cents=account.balance_cents,
    )


@router.post("/guest", response_model=AuthMeRead)
def post_guest(response: Response, request: Request, db: Session = Depends(get_db)) -> AuthMeRead:
    user, account, token = auth_service.login_guest(db, user_agent=_user_agent(request))
    db.commit()
    _set_auth_cookie(response, token)
    return AuthMeRead(
        user=UserRead.model_validate(user),
        account_id=account.id,
        balance_cents=account.balance_cents,
    )


@router.post("/logout", status_code=204)
def post_logout(response: Response, request: Request, db: Session = Depends(get_db)) -> Response:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    auth_service.revoke_session(db, token)
    db.commit()
    _clear_auth_cookie(response)
    return response


@router.get("/me", response_model=AuthMeRead)
def get_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> AuthMeRead:
    account = auth_service.current_account_for_user(db, user)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found for user")
    return AuthMeRead(
        user=UserRead.model_validate(user),
        account_id=account.id,
        balance_cents=account.balance_cents,
    )
