"""Product analytics events. No third-party collector."""

from app.services.product_analytics.service import plan, record_event, stored_events

__all__ = ["plan", "record_event", "stored_events"]
