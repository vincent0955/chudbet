from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import secrets
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Account, User, UserSession
from app.services import money

SCRYPT_N: Final[int] = 2**14
SCRYPT_R: Final[int] = 8
SCRYPT_P: Final[int] = 1
SCRYPT_DKLEN: Final[int] = 64

GUEST_STARTING_CENTS: Final[int] = 10_000
SESSION_TTL_DAYS: Final[int] = 30


def _utcnow() -> datetime:
    return datetime.now(UTC)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return "scrypt$%d$%d$%d$%s$%s" % (
        SCRYPT_N,
        SCRYPT_R,
        SCRYPT_P,
        salt.hex(),
        derived.hex(),
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algo, n_raw, r_raw, p_raw, salt_hex, expected_hex = stored_hash.split("$", 5)
        if algo != "scrypt":
            return False
        n = int(n_raw)
        r = int(r_raw)
        p = int(p_raw)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(expected_hex)
    except Exception:
        return False
    actual = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=len(expected),
    )
    return hmac.compare_digest(actual, expected)


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _normalize_username(username: str) -> str:
    return username.strip().lower()


def _session_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _create_session(session: Session, user: User, user_agent: str | None = None) -> tuple[str, UserSession]:
    token = secrets.token_urlsafe(48)
    row = UserSession(
        user_id=user.id,
        token_hash=_session_token_hash(token),
        user_agent=user_agent,
        expires_at=_utcnow() + timedelta(days=SESSION_TTL_DAYS),
        revoked_at=None,
    )
    session.add(row)
    session.flush()
    return token, row


def _ensure_primary_account(session: Session, user: User, *, seed_guest: bool) -> Account:
    existing = session.scalar(
        select(Account).where(Account.user_id == user.id).order_by(Account.id.asc()).limit(1)
    )
    if existing is not None:
        return existing
    account = money.create_account(session, user_id=user.id)
    if seed_guest:
        money.deposit(
            session,
            account.id,
            amount_cents=GUEST_STARTING_CENTS,
            idempotency_key=f"guest-seed-v1-user-{user.id}",
            memo="Guest starting balance",
        )
    session.flush()
    return account


def signup_user(
    session: Session,
    *,
    email: str,
    username: str,
    password: str,
    user_agent: str | None = None,
) -> tuple[User, Account, str]:
    email_norm = _normalize_email(email)
    username_norm = _normalize_username(username)
    exists = session.scalar(select(User).where(User.email == email_norm))
    if exists is not None:
        raise ValueError("email already in use")
    name_exists = session.scalar(select(User).where(User.username == username_norm))
    if name_exists is not None:
        raise ValueError("username already in use")
    user = User(email=email_norm, username=username_norm, password_hash=hash_password(password), is_guest=False)
    session.add(user)
    session.flush()
    account = _ensure_primary_account(session, user, seed_guest=False)
    token, _ = _create_session(session, user, user_agent=user_agent)
    return user, account, token


def login_user(
    session: Session,
    *,
    email: str,
    password: str,
    user_agent: str | None = None,
) -> tuple[User, Account, str]:
    email_norm = _normalize_email(email)
    user = session.scalar(select(User).where(User.email == email_norm))
    if user is None or not verify_password(password, user.password_hash):
        raise ValueError("invalid email or password")
    account = _ensure_primary_account(session, user, seed_guest=False)
    token, _ = _create_session(session, user, user_agent=user_agent)
    return user, account, token


def login_guest(session: Session, *, user_agent: str | None = None) -> tuple[User, Account, str]:
    guest_email = f"guest-{secrets.token_hex(8)}@guest.local"
    guest_username = f"guest-{secrets.token_hex(6)}"
    while session.scalar(select(User).where(User.username == guest_username)) is not None:
        guest_username = f"guest-{secrets.token_hex(6)}"
    user = User(
        email=guest_email,
        username=guest_username,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        is_guest=True,
    )
    session.add(user)
    session.flush()
    account = _ensure_primary_account(session, user, seed_guest=True)
    token, _ = _create_session(session, user, user_agent=user_agent)
    return user, account, token


def resolve_session_user(session: Session, token: str | None) -> User | None:
    if token is None or not token.strip():
        return None
    token_hash = _session_token_hash(token.strip())
    now = _utcnow()
    row = session.scalar(
        select(UserSession).where(
            UserSession.token_hash == token_hash,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
    )
    if row is None:
        return None
    return session.get(User, row.user_id)


def revoke_session(session: Session, token: str | None) -> None:
    if token is None or not token.strip():
        return
    token_hash = _session_token_hash(token.strip())
    row = session.scalar(select(UserSession).where(UserSession.token_hash == token_hash))
    if row is None or row.revoked_at is not None:
        return
    row.revoked_at = _utcnow()
    session.flush()


def current_account_for_user(session: Session, user: User) -> Account | None:
    return session.scalar(select(Account).where(Account.user_id == user.id).order_by(Account.id.asc()).limit(1))
