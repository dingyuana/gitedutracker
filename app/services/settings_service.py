from sqlmodel import Session

from app.config import Settings, get_settings
from app.models import LlmConfig, SmtpConfig


def save_llm_config(
    session: Session,
    llm_model: str = "",
    llm_base_url: str = "",
    llm_api_key: str = "",
    llm_context_max_chars: int | None = None,
) -> LlmConfig:
    row = session.get(LlmConfig, 1)
    if row is None:
        row = LlmConfig(id=1)
        session.add(row)

    if llm_base_url.strip():
        row.llm_base_url = llm_base_url.strip()
    if llm_api_key.strip():
        row.llm_api_key = llm_api_key.strip()
    if llm_model.strip():
        row.llm_model = llm_model.strip()
    if llm_context_max_chars:
        row.llm_context_max_chars = int(llm_context_max_chars)

    from datetime import datetime, timezone
    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def get_llm_config(session: Session) -> LlmConfig | None:
    return session.get(LlmConfig, 1)


def save_smtp_config(
    session: Session,
    smtp_host: str = "",
    smtp_port: int | None = None,
    smtp_user: str = "",
    smtp_pass: str = "",
    smtp_from: str = "",
) -> SmtpConfig:
    row = session.get(SmtpConfig, 1)
    if row is None:
        row = SmtpConfig(id=1)
        session.add(row)

    if smtp_host.strip():
        row.smtp_host = smtp_host.strip()
    if smtp_port:
        row.smtp_port = int(smtp_port)
    if smtp_user.strip():
        row.smtp_user = smtp_user.strip()
    if smtp_pass.strip():
        row.smtp_pass = smtp_pass.strip()
    if smtp_from.strip():
        row.smtp_from = smtp_from.strip()

    from datetime import datetime, timezone
    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def get_smtp_config(session: Session) -> SmtpConfig | None:
    return session.get(SmtpConfig, 1)


def get_effective_settings(session: Session) -> Settings:
    base = get_settings()
    updates = {}
    row = get_llm_config(session)
    if row is not None:
        for field in ("llm_base_url", "llm_api_key", "llm_model", "llm_context_max_chars"):
            value = getattr(row, field)
            if value:
                updates[field] = value
    smtp = get_smtp_config(session)
    if smtp is not None:
        for field in ("smtp_host", "smtp_port", "smtp_user", "smtp_pass", "smtp_from"):
            value = getattr(smtp, field)
            if value:
                updates[field] = value
    if not updates:
        return base
    return base.model_copy(update=updates)
