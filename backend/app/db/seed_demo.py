"""Optional dev/demo wallet with a fixed account id and seeded balance (see env vars)."""

from __future__ import annotations

import logging
import os

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import session as db_session
from app.db.models import Account
from app.services import money

logger = logging.getLogger(__name__)


def _truthy(raw: str | None) -> bool:
    if raw is None:
        return False
    return raw.strip().lower() in ("1", "true", "yes")


def _bump_accounts_id_seq(session: Session) -> None:
    bind = session.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return
    session.execute(
        text(
            "SELECT setval(pg_get_serial_sequence('accounts', 'id'), "
            "(SELECT COALESCE(MAX(id), 1) FROM accounts))"
        )
    )


def seed_demo_wallet_if_enabled() -> None:
    """
    When CHUDBET_SEED_DEMO_WALLET is truthy, ensure account id CHUDBET_DEMO_ACCOUNT_ID (default 1)
    exists with balance from CHUDBET_DEMO_WALLET_CENTS via a single idempotent ledger deposit.
    """
    if not _truthy(os.getenv("CHUDBET_SEED_DEMO_WALLET")):
        return
    account_id = int(os.getenv("CHUDBET_DEMO_ACCOUNT_ID", "1"))
    initial_cents = int(os.getenv("CHUDBET_DEMO_WALLET_CENTS", "10000000"))

    db_session.get_engine()
    factory = db_session.SessionLocal
    if factory is None:
        logger.warning("Demo wallet seed skipped: SessionLocal missing")
        return
    db = factory()
    try:
        if db.get(Account, account_id) is not None:
            logger.info("Demo wallet seed skipped: account %s already exists", account_id)
            return

        db.add(Account(id=account_id, balance_cents=0))
        db.flush()
        _, entry, _ = money.deposit(
            db,
            account_id,
            amount_cents=initial_cents,
            idempotency_key="chudbet_seed_demo_wallet_v1",
            memo="Demo wallet seed",
        )
        _bump_accounts_id_seq(db)
        db.commit()
        logger.info(
            "Seeded demo wallet account_id=%s balance_cents=%s ledger_entry_id=%s",
            account_id,
            initial_cents,
            entry.id,
        )
    except Exception:
        db.rollback()
        logger.exception("Demo wallet seed failed")
    finally:
        db.close()
