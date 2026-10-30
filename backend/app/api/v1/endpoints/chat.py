"""In-app chat REST API (Prompt 75)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_email, get_db
from app.core.rbac_deps import get_identity_for_email, get_user_and_role
from app.domain.chat import ConversationCreate, ConversationRead, MessageCreate, MessageRead
from app.domain.rbac import SystemRole, has_permission
from app.services.chat.service import ChatAccessError, chat_service
from app.utils.ws_notify import notify_chat_sync

router = APIRouter(prefix="/chat", tags=["chat"])


async def _chat_context(db: AsyncSession, email: str):
    user, role = await get_user_and_role(db, email)
    identity = await get_identity_for_email(db, email)
    return user, role, identity


@router.get("/conversations")
async def list_conversations(
    related_symbol: str | None = None,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user, role, identity = await _chat_context(db, email)
    if not has_permission(role, "chat.read"):
        raise HTTPException(403, "Нет доступа к чату")
    try:
        items = await chat_service.list_conversations(
            db,
            identity=identity,
            user_id=user.id,
            system_role=role,
            related_symbol=related_symbol,
        )
    except ChatAccessError as exc:
        raise HTTPException(403, "Нет доступа к этому чату") from exc
    return {"items": [i.model_dump(mode="json") for i in items]}


@router.post("/conversations", response_model=ConversationRead, status_code=201)
async def create_conversation(
    body: ConversationCreate,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user, role, identity = await _chat_context(db, email)
    try:
        conv = await chat_service.create_conversation(
            db,
            client_profile_id=user.id,
            body=body,
            identity=identity,
            user_id=user.id,
            system_role=role,
        )
    except ChatAccessError as exc:
        raise HTTPException(403, "Нет доступа к этому чату") from exc
    except ValueError as exc:
        raise HTTPException(400, "Проверьте запрос и попробуйте снова") from exc
    await db.commit()
    return conv


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user, role, identity = await _chat_context(db, email)
    try:
        items = await chat_service.list_messages(
            db,
            conversation_id,
            identity=identity,
            user_id=user.id,
            system_role=role,
        )
    except ChatAccessError as exc:
        raise HTTPException(403, "Нет доступа к этому чату") from exc
    except LookupError as exc:
        raise HTTPException(404, "Чат не найден") from exc
    return {"items": [i.model_dump(mode="json") for i in items]}


@router.post("/conversations/{conversation_id}/messages", response_model=MessageRead, status_code=201)
async def post_message(
    conversation_id: str,
    body: MessageCreate,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user, role, identity = await _chat_context(db, email)
    try:
        msg = await chat_service.send_message(
            db,
            conversation_id,
            identity=identity,
            user_id=user.id,
            system_role=role,
            body=body,
        )
    except ChatAccessError as exc:
        raise HTTPException(403, "Нет доступа к этому чату") from exc
    except LookupError as exc:
        raise HTTPException(404, "Чат не найден") from exc
    except ValueError as exc:
        raise HTTPException(400, "Проверьте запрос и попробуйте снова") from exc
    await db.commit()
    notify_chat_sync(conversation_id, msg.model_dump(mode="json"))
    return msg


@router.post("/conversations/deal-intent/{deal_intent_id}", response_model=ConversationRead, status_code=201)
async def get_or_create_for_deal_intent(
    deal_intent_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user, role, identity = await _chat_context(db, email)
    try:
        conv = await chat_service.get_or_create_for_deal_intent(
            db,
            deal_intent_id=deal_intent_id,
            client_profile_id=user.id,
            identity=identity,
            user_id=user.id,
            system_role=role,
        )
    except ChatAccessError as exc:
        raise HTTPException(403, "Нет доступа к этому чату") from exc
    await db.commit()
    return conv


@router.post("/conversations/ticker/{symbol}", response_model=ConversationRead, status_code=201)
async def get_or_create_for_ticker(
    symbol: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user, role, identity = await _chat_context(db, email)
    if not has_permission(role, "chat.read"):
        raise HTTPException(403, "Нет доступа к чату")
    try:
        conv = await chat_service.get_or_create_for_symbol(
            db,
            symbol=symbol,
            client_profile_id=user.id,
            identity=identity,
            user_id=user.id,
            system_role=role,
        )
    except ChatAccessError as exc:
        raise HTTPException(403, "Нет доступа к этому чату") from exc
    await db.commit()
    return conv


@router.post("/conversations/{conversation_id}/archive", response_model=ConversationRead)
async def archive_conversation(
    conversation_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user, role, identity = await _chat_context(db, email)
    try:
        conv = await chat_service.archive_conversation(
            db,
            conversation_id,
            identity=identity,
            user_id=user.id,
            system_role=role,
        )
    except ChatAccessError as exc:
        raise HTTPException(403, "Нет доступа к этому чату") from exc
    except LookupError as exc:
        raise HTTPException(404, "Чат не найден") from exc
    await db.commit()
    return conv


@router.post("/conversations/{conversation_id}/ask-ai")
async def ask_advisor(
    conversation_id: str,
    body: MessageCreate,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user, role, identity = await _chat_context(db, email)
    try:
        user_msg, advisor_msg = await chat_service.ask_advisor(
            db,
            conversation_id,
            identity=identity,
            user_id=user.id,
            system_role=role,
            body=body,
        )
    except ChatAccessError as exc:
        raise HTTPException(403, "Нет доступа к этому чату") from exc
    except LookupError as exc:
        raise HTTPException(404, "Чат не найден") from exc
    except ValueError as exc:
        raise HTTPException(400, "Проверьте запрос и попробуйте снова") from exc
    await db.commit()
    notify_chat_sync(conversation_id, user_msg.model_dump(mode="json"))
    notify_chat_sync(conversation_id, advisor_msg.model_dump(mode="json"))
    return {
        "user_message": user_msg.model_dump(mode="json"),
        "advisor_message": advisor_msg.model_dump(mode="json"),
    }
