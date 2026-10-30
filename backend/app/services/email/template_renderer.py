"""Jinja2 template rendering with DB-backed versioned store."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.email_transactional import EmailTemplateORM

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

# Bundled defaults — DB overrides take precedence when active.
_BUNDLED: dict[str, dict[str, str]] = {
    "password_recovery": {
        "subject": "Quant Analytics — reset your password",
        "html": "password_recovery.html.j2",
        "text": "password_recovery.txt.j2",
    },
    "password_changed": {
        "subject": "Quant Analytics — your password was changed",
        "html": "password_changed.html.j2",
        "text": "password_changed.txt.j2",
    },
    "email_verification": {
        "subject": "Quant Analytics — verify your email",
        "html": "email_verification.html.j2",
        "text": "email_verification.txt.j2",
    },
}


def _email_logo_url() -> str:
    base = settings.EMAIL_VERIFICATION_BASE_URL.rstrip("/")
    return f"{base}/branding/qa-logo-solid-navy.png"


def _with_branding(variables: dict) -> dict:
    merged = dict(variables)
    merged.setdefault("logo_url", _email_logo_url())
    return merged


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    html_body: str
    text_body: str
    template_name: str
    template_version: int


async def render_template(
    db: AsyncSession,
    name: str,
    variables: dict,
) -> RenderedEmail:
    """Render email from active DB template or bundled Jinja2 fallback."""
    result = await db.execute(
        select(EmailTemplateORM)
        .where(EmailTemplateORM.name == name, EmailTemplateORM.is_active.is_(True))
        .order_by(EmailTemplateORM.version.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row:
        branded = _with_branding(variables)
        html = Environment(autoescape=select_autoescape(["html", "xml"])).from_string(
            row.html_body
        ).render(**branded)
        text = Environment(autoescape=False).from_string(row.text_body).render(**branded)
        subject = Environment(autoescape=False).from_string(row.subject).render(**branded)
        return RenderedEmail(
            subject=subject,
            html_body=html,
            text_body=text,
            template_name=name,
            template_version=row.version,
        )

    bundled = _BUNDLED.get(name)
    if not bundled:
        raise ValueError(f"Unknown email template: {name}")

    branded = _with_branding(variables)
    html_tpl = _jinja_env.get_template(bundled["html"])
    text_tpl = _jinja_env.get_template(bundled["text"])
    return RenderedEmail(
        subject=bundled["subject"],
        html_body=html_tpl.render(**branded),
        text_body=text_tpl.render(**branded),
        template_name=name,
        template_version=0,
    )
