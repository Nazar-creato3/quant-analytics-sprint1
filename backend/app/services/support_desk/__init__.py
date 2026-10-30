"""Support reports. No mail and no Slack call."""

from app.services.support_desk.service import frequent, known_issues, report

__all__ = ["frequent", "known_issues", "report"]
