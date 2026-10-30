"""D-18-1 clarification: act-step and AI texts reject advice wording."""
from __future__ import annotations

from pathlib import Path

from app.services.explanations.service import filter_wording
from app.services.qa.feature_flags import is_enabled, reset_for_tests

REPO = Path(__file__).resolve().parents[3]
FORBIDDEN = (
    "рекомендуем",
    "советуем",
    "подходит вам",
    "соответствует вашему профилю",
)
SCAN = (
    "backend/app/services/act_desk/service.py",
    "backend/app/services/maneuvers/service.py",
    "backend/app/services/maneuver_cycle/service.py",
    "backend/app/services/maneuver_cycle/pdf.py",
    "backend/app/services/maneuver_control/service.py",
    "backend/app/services/order_machine/service.py",
    "backend/app/services/partners/service.py",
    "backend/app/services/subscription_billing/service.py",
    "backend/app/services/bot_core/service.py",
    "backend/app/services/ops_observe/service.py",
    "backend/app/services/perf_budget/service.py",
    "frontend/src/lib/public-methodology.ts",
    "frontend/src/lib/public-site.ts",
    "backend/app/services/waitlist/service.py",
    "frontend/src/lib/waitlist.ts",
    "backend/app/services/public_accuracy/service.py",
    "frontend/src/lib/public-accuracy.ts",
    "backend/app/services/product_analytics/service.py",
    "frontend/src/lib/product-analytics.ts",
    "backend/app/services/product_analytics/metrics.py",
    "frontend/src/lib/founder-metrics.ts",
    "backend/app/services/experiments/service.py",
    "frontend/src/lib/experiments.ts",
    "backend/app/services/beta_admin/service.py",
    "frontend/src/lib/beta-admin.ts",
    "backend/app/services/subject_rights/service.py",
    "frontend/src/lib/subject-rights.ts",
    "backend/app/services/support_desk/service.py",
    "frontend/src/lib/support-desk.ts",
    "frontend/src/components/act/ManeuverCycleCard.tsx",
    "frontend/src/app/act/page.tsx",
    "backend/app/services/explanations/templates.json",
    "backend/app/services/chat/advisor_prompt.py",
    "backend/app/services/chat/deep_advisor.py",
    "backend/app/services/chat/ticker_advisor.py",
    "backend/app/services/chat/agentic_advisor.py",
    "backend/app/services/chat/llm_advisor.py",
    "backend/app/services/ops_observe/service.py",
    "backend/app/services/perf_budget/service.py",
    "docs/methodology/public-overview.md",
)


def test_act_and_ai_texts_omit_forbidden_advice():
    for rel in SCAN:
        text = (REPO / rel).read_text(encoding="utf-8").lower()
        for phrase in FORBIDDEN:
            assert phrase not in text, f"{rel} contains {phrase}"
    templates = (REPO / "backend/app/services/explanations/templates.json").read_text(encoding="utf-8")
    assert "это возвращает портфель к вашим правилам" in templates.lower()
    assert filter_wording(templates) == []


def test_maneuver_flags_match_founder_list():
    reset_for_tests()
    assert is_enabled("qa_act_live") is False
    assert is_enabled("qa_maneuvers_user_rules") is False
    assert is_enabled("qa_act_model_profile") is False
    assert is_enabled("qa_display_unlicensed") is False
    assert is_enabled("qa_investment_profile") is True
    assert is_enabled("qa_act_desk") is True
    act = (REPO / "backend/app/services/act_desk/service.py").read_text(encoding="utf-8")
    assert '"target_source": "user"' in act
    assert "режим «под профиль» выключен" in act
