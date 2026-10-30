"""Tests for compliance PDF report generation."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.deal_intents import router as deal_intents_router
from app.core.deps import get_current_user_email, get_db
from app.services.compliance_report.pdf_renderer import render_compliance_pdf
from app.services.compliance_report.types import ComplianceReportDocument


def _sample_document() -> ComplianceReportDocument:
    return ComplianceReportDocument(
        report_id="rep-1",
        generated_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
        deal_intent_id="intent-abc",
        instrument_symbol="SPY",
        instrument_id=1,
        direction="long",
        strategy="trend",
        status="approved",
        entry_reason="Momentum breakout",
        target_price="520.00",
        risk_appetite="moderate",
        max_drawdown_pct="15.00",
        jurisdiction="ru",
        account_type="retail",
        explainability_headline="Режим trend сохраняется.",
        explainability_sections=(("Режим рынка", "Уверенность 0.72."),),
        narrator_insights=("ApprovalPolicyEngine: auto_approve.",),
        audit_reference="audit_log:1 @ 2026-07-22T00:00:00+00:00",
    )


class TestCompliancePdfRenderer:
    def test_render_produces_pdf_bytes(self):
        pdf = render_compliance_pdf(_sample_document())
        assert pdf.startswith(b"%PDF")
        assert len(pdf) > 500


class TestComplianceReportEndpoint:
    @pytest.fixture
    def client(self):
        app = FastAPI()
        app.include_router(deal_intents_router, prefix="/api/v1")

        async def _db():
            yield AsyncMock()

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user_email] = lambda: "user@test.com"
        return TestClient(app)

    @patch("app.api.v1.endpoints.deal_intents.ComplianceReportService")
    def test_download_pdf(self, service_cls, client):
        service = service_cls.return_value
        service.build_document = AsyncMock(return_value=_sample_document())

        response = client.get("/api/v1/deal-intents/intent-abc/compliance-report.pdf")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content.startswith(b"%PDF")

    @patch("app.api.v1.endpoints.deal_intents.ComplianceReportService")
    def test_missing_intent_returns_404(self, service_cls, client):
        from app.services.compliance_report.service import ComplianceReportNotFoundError

        service = service_cls.return_value
        service.build_document = AsyncMock(
            side_effect=ComplianceReportNotFoundError("missing")
        )

        response = client.get("/api/v1/deal-intents/missing/compliance-report.pdf")
        assert response.status_code == 404
