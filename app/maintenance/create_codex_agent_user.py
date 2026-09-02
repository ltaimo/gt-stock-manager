from __future__ import annotations

from app.database import SessionLocal
from app.seed import CODEX_AGENT_USERNAME, ensure_codex_agent_user


def create_codex_agent_user() -> str:
    with SessionLocal() as db:
        action = ensure_codex_agent_user(db)
        db.commit()
        return action


if __name__ == "__main__":
    action = create_codex_agent_user()
    print(f"{action}: {CODEX_AGENT_USERNAME}")
