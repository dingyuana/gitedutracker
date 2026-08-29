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


_SMTP_DOMAIN_MAP = {
    "qq.com": ("smtp.qq.com", 587),
    "163.com": ("smtp.163.com", 587),
    "126.com": ("smtp.126.com", 587),
    "gmail.com": ("smtp.gmail.com", 587),
    "outlook.com": ("smtp-mail.outlook.com", 587),
    "foxmail.com": ("smtp.qq.com", 587),
}


_PLACEHOLDER_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0"}


def infer_smtp_settings(email: str, explicit_host: str = "",
                        explicit_port: int | None = None) -> tuple[str, int]:
    """根据邮箱地址推断 SMTP host/port；显式传入的自定义 host/port 优先（占位值除外）。"""
    domain = (email.strip() or "").split("@")[-1].lower()
    inferred_host, inferred_port = _SMTP_DOMAIN_MAP.get(domain, (f"smtp.{domain}", 587))
    if explicit_host.strip() and explicit_host.strip().lower() not in _PLACEHOLDER_HOSTS:
        return explicit_host.strip(), explicit_port or inferred_port
    return inferred_host, inferred_port


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

    user = smtp_user.strip() or (row.smtp_user or "")
    host, port = infer_smtp_settings(user, smtp_host, smtp_port)
    row.smtp_host = host
    row.smtp_port = port
    if smtp_user.strip():
        row.smtp_user = user
    if smtp_pass.strip():
        row.smtp_pass = smtp_pass.strip()
    row.smtp_from = smtp_from.strip() or user

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
