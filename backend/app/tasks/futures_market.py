from app.tasks.celery_app import celery_app
from app.services.futures_market.service import explain_market


@celery_app.task(name="app.tasks.futures_market.rebuild_futures_market")
def rebuild_futures_market() -> dict:
    payload = explain_market("MIX", user_token=False)
    return {"status": payload.get("data_status"), "ticker": "MIX"}
