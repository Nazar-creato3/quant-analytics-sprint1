"""In-app chat service with RBAC-scoped access (Prompt 75)."""
from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

from app.domain.chat import (
    ConversationCreate,
    ConversationORM,
    ConversationRead,
    ConversationStatus,
    MessageCreate,
    MessageORM,
    MessageRead,
    MessageSenderRole,
)
from app.domain.rbac import IdentityORM, SystemRole, has_permission, map_legacy_user_role
from app.services.chat.ticker_advisor import (
    advisor_sender_id,
    build_ticker_advisor_reply,
    default_ticker_title,
    extract_symbol_from_text,
)
from app.services.chat.context_isolation import (
    prior_messages_for_symbol,
    resolve_advisor_symbol,
)
from app.utils.helpers import new_uuid, utcnow

logger = get_logger(__name__)


class ChatAccessError(PermissionError):
    pass


class ChatService:
    def _normalize_symbol(self, symbol: str | None) -> str | None:
        if not symbol:
            return None
        cleaned = symbol.strip().upper()
        return cleaned or None

    async def _find_open_conversation_for_symbol(
        self,
        db: AsyncSession,
        *,
        client_profile_id: str,
        symbol: str,
    ) -> ConversationORM | None:
        normalized = self._normalize_symbol(symbol)
        if not normalized:
            return None
        result = await db.execute(
            select(ConversationORM)
            .where(
                ConversationORM.client_profile_id == client_profile_id,
                func.upper(ConversationORM.related_symbol) == normalized,
                ConversationORM.status != ConversationStatus.ARCHIVED.value,
            )
            .order_by(ConversationORM.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    def _truncate_title(self, text: str, max_len: int = 80) -> str:
        cleaned = " ".join(text.split())
        if len(cleaned) <= max_len:
            return cleaned
        return cleaned[: max_len - 1].rstrip() + "…"

    def _title_from_question(self, question: str, symbol: str | None = None) -> str:
        title = self._truncate_title(question)
        if symbol and symbol.upper() not in title.upper():
            title = f"{symbol.upper()}, {title[0].lower()}{title[1:]}" if title else symbol.upper()
        return title

    async def _maybe_update_title_from_question(
        self,
        db: AsyncSession,
        conv: ConversationORM,
        question: str,
        *,
        symbol: str | None = None,
    ) -> None:
        sym = symbol or conv.related_symbol
        default = default_ticker_title(sym) if sym else None
        if conv.title and default and conv.title != default:
            return
        conv.title = self._title_from_question(question, sym)
        await db.flush()

    def sender_role_for(self, system_role: SystemRole) -> MessageSenderRole:
        if system_role == SystemRole.OWNER_ADMIN:
            return MessageSenderRole.OWNER_ADMIN
        if system_role == SystemRole.OPERATOR_ADMIN:
            return MessageSenderRole.OPERATOR_ADMIN
        return MessageSenderRole.CLIENT

    async def list_conversations(
        self,
        db: AsyncSession,
        *,
        identity: IdentityORM | None,
        user_id: str,
        system_role: SystemRole,
        related_symbol: str | None = None,
    ) -> list[ConversationRead]:
        q = select(ConversationORM).order_by(ConversationORM.created_at.desc())
        if system_role == SystemRole.USER:
            q = q.where(ConversationORM.client_profile_id == user_id)
        elif system_role == SystemRole.OPERATOR_ADMIN:
            if not has_permission(system_role, "chat.queue"):
                raise ChatAccessError("chat.queue required")
            admin_id = identity.id if identity else None
            q = q.where(
                or_(
                    ConversationORM.assigned_admin_id.is_(None),
                    ConversationORM.assigned_admin_id == admin_id,
                )
            )
        elif not has_permission(system_role, "*"):
            raise ChatAccessError("chat.read denied")

        normalized_symbol = self._normalize_symbol(related_symbol)
        if normalized_symbol:
            q = q.where(func.upper(ConversationORM.related_symbol) == normalized_symbol)

        result = await db.execute(q.limit(200))
        return [ConversationRead.model_validate(row) for row in result.scalars().all()]

    async def get_conversation(
        self,
        db: AsyncSession,
        conversation_id: str,
        *,
        identity: IdentityORM | None,
        user_id: str,
        system_role: SystemRole,
    ) -> ConversationORM:
        result = await db.execute(
            select(ConversationORM).where(ConversationORM.id == conversation_id)
        )
        conv = result.scalar_one_or_none()
        if not conv:
            raise LookupError("Conversation not found")
        if not await self._can_access(db, conv, identity=identity, user_id=user_id, system_role=system_role):
            raise ChatAccessError("Conversation access denied")
        return conv

    async def list_messages(
        self,
        db: AsyncSession,
        conversation_id: str,
        *,
        identity: IdentityORM | None,
        user_id: str,
        system_role: SystemRole,
        limit: int = 100,
    ) -> list[MessageRead]:
        await self.get_conversation(
            db, conversation_id, identity=identity, user_id=user_id, system_role=system_role
        )
        result = await db.execute(
            select(MessageORM)
            .where(MessageORM.conversation_id == conversation_id)
            .order_by(MessageORM.created_at.asc())
            .limit(min(limit, 500))
        )
        return [MessageRead.model_validate(row) for row in result.scalars().all()]

    async def send_message(
        self,
        db: AsyncSession,
        conversation_id: str,
        *,
        identity: IdentityORM | None,
        user_id: str,
        system_role: SystemRole,
        body: MessageCreate,
    ) -> MessageRead:
        conv = await self.get_conversation(
            db, conversation_id, identity=identity, user_id=user_id, system_role=system_role
        )
        if not has_permission(system_role, "chat.write"):
            raise ChatAccessError("chat.write denied")
        if conv.status == ConversationStatus.ARCHIVED.value:
            raise ValueError("Conversation archived")

        msg = MessageORM(
            id=new_uuid(),
            conversation_id=conversation_id,
            sender_id=user_id,
            sender_role=self.sender_role_for(system_role).value,
            body=body.body.strip(),
            attachment_url=body.attachment_url,
        )
        db.add(msg)
        await db.flush()
        return MessageRead.model_validate(msg)

    async def create_conversation(
        self,
        db: AsyncSession,
        *,
        client_profile_id: str,
        body: ConversationCreate,
        identity: IdentityORM | None,
        user_id: str,
        system_role: SystemRole,
    ) -> ConversationRead:
        if system_role == SystemRole.USER and client_profile_id != user_id:
            raise ChatAccessError("Cannot create conversation for another client")
        if system_role != SystemRole.USER and not has_permission(system_role, "chat.write"):
            raise ChatAccessError("chat.write denied")

        if body.related_deal_intent_id:
            existing = await db.execute(
                select(ConversationORM).where(
                    ConversationORM.client_profile_id == client_profile_id,
                    ConversationORM.related_deal_intent_id == body.related_deal_intent_id,
                    ConversationORM.status != ConversationStatus.ARCHIVED.value,
                )
            )
            found = existing.scalar_one_or_none()
            if found:
                conv = found
            else:
                conv = ConversationORM(
                    id=new_uuid(),
                    client_profile_id=client_profile_id,
                    related_deal_intent_id=body.related_deal_intent_id,
                    status=ConversationStatus.OPEN.value,
                )
                db.add(conv)
                await db.flush()
        elif body.related_symbol:
            symbol = self._normalize_symbol(body.related_symbol)
            if not symbol:
                raise ValueError("related_symbol required")
            found = await self._find_open_conversation_for_symbol(
                db,
                client_profile_id=client_profile_id,
                symbol=symbol,
            )
            if found:
                conv = found
            else:
                conv = ConversationORM(
                    id=new_uuid(),
                    client_profile_id=client_profile_id,
                    related_symbol=symbol,
                    title=default_ticker_title(symbol),
                    status=ConversationStatus.OPEN.value,
                )
                db.add(conv)
                await db.flush()
        else:
            conv = ConversationORM(
                id=new_uuid(),
                client_profile_id=client_profile_id,
                status=ConversationStatus.OPEN.value,
            )
            db.add(conv)
            await db.flush()

        if body.initial_message:
            await self.send_message(
                db,
                conv.id,
                identity=identity,
                user_id=user_id,
                system_role=system_role,
                body=MessageCreate(body=body.initial_message),
            )

        return ConversationRead.model_validate(conv)

    async def get_or_create_for_deal_intent(
        self,
        db: AsyncSession,
        *,
        deal_intent_id: str,
        client_profile_id: str,
        identity: IdentityORM | None,
        user_id: str,
        system_role: SystemRole,
    ) -> ConversationRead:
        return await self.create_conversation(
            db,
            client_profile_id=client_profile_id,
            body=ConversationCreate(related_deal_intent_id=deal_intent_id),
            identity=identity,
            user_id=user_id,
            system_role=system_role,
        )

    async def get_or_create_for_symbol(
        self,
        db: AsyncSession,
        *,
        symbol: str,
        client_profile_id: str,
        identity: IdentityORM | None,
        user_id: str,
        system_role: SystemRole,
    ) -> ConversationRead:
        return await self.create_conversation(
            db,
            client_profile_id=client_profile_id,
            body=ConversationCreate(related_symbol=symbol.strip().upper()),
            identity=identity,
            user_id=user_id,
            system_role=system_role,
        )

    async def archive_conversation(
        self,
        db: AsyncSession,
        conversation_id: str,
        *,
        identity: IdentityORM | None,
        user_id: str,
        system_role: SystemRole,
    ) -> ConversationRead:
        conv = await self.get_conversation(
            db, conversation_id, identity=identity, user_id=user_id, system_role=system_role
        )
        if not has_permission(system_role, "chat.write"):
            raise ChatAccessError("chat.write denied")
        if conv.status != ConversationStatus.ARCHIVED.value:
            conv.status = ConversationStatus.ARCHIVED.value
            await db.flush()
        return ConversationRead.model_validate(conv)

    async def ask_advisor(
        self,
        db: AsyncSession,
        conversation_id: str,
        *,
        identity: IdentityORM | None,
        user_id: str,
        system_role: SystemRole,
        body: MessageCreate,
    ) -> tuple[MessageRead, MessageRead]:
        conv = await self.get_conversation(
            db, conversation_id, identity=identity, user_id=user_id, system_role=system_role
        )
        if not has_permission(system_role, "chat.write"):
            raise ChatAccessError("chat.write denied")
        if conv.status == ConversationStatus.ARCHIVED.value:
            raise ValueError("Conversation archived")

        question = body.body.strip()
        symbol = resolve_advisor_symbol(question, conv.related_symbol)

        user_msg = MessageORM(
            id=new_uuid(),
            conversation_id=conversation_id,
            sender_id=user_id,
            sender_role=self.sender_role_for(system_role).value,
            body=question,
            attachment_url=body.attachment_url,
        )
        db.add(user_msg)
        await db.flush()

        await self._maybe_update_title_from_question(db, conv, question, symbol=symbol)

        history_rows = await db.execute(
            select(MessageORM.sender_role, MessageORM.body)
            .where(MessageORM.conversation_id == conversation_id)
            .order_by(MessageORM.created_at.asc())
            .limit(40)
        )
        conversation_history: list[tuple[str, str]] = []
        session_tickers: set[str] = set()
        for role_val, body_text in history_rows.all():
            if role_val == MessageSenderRole.CLIENT.value:
                conversation_history.append(("user", body_text))
            elif role_val == MessageSenderRole.ADVISOR_AI.value:
                conversation_history.append(("assistant", body_text))
            extracted = extract_symbol_from_text(body_text)
            if extracted:
                session_tickers.add(extracted)
        if symbol:
            session_tickers.add(symbol.upper())

        prior_msgs = await db.execute(
            select(MessageORM.body)
            .where(
                MessageORM.conversation_id == conversation_id,
                MessageORM.sender_role == MessageSenderRole.ADVISOR_AI.value,
            )
            .order_by(MessageORM.created_at.desc())
            .limit(3)
        )
        prior_bodies = prior_messages_for_symbol(
            tuple(row[0] for row in prior_msgs.all()),
            symbol or "",
        )

        reply_text: str
        if symbol:
            try:
                reply_text = await build_ticker_advisor_reply(
                    db,
                    symbol=symbol,
                    user_question=question,
                    prior_messages=prior_bodies,
                    conversation_history=conversation_history[:-1] if conversation_history else None,
                    session_tickers=list(session_tickers) if session_tickers else None,
                    owner_user_id=user_id,
                )
            except Exception as exc:  # noqa: BLE001
                reply_text = (
                    f"Не удалось построить прогноз по {symbol}. "
                    "Повторите через минуту или откройте вкладку Forecast."
                )
                logger.warning(
                    "Advisor reply failed",
                    symbol=symbol,
                    error=str(exc),
                )
        else:
            from app.services.chat.ticker_advisor import build_open_chat_reply

            try:
                reply_text = await build_open_chat_reply(
                    db,
                    user_question=question,
                    conversation_history=conversation_history[:-1] if conversation_history else None,
                    session_tickers=list(session_tickers) if session_tickers else None,
                    owner_user_id=user_id,
                )
            except Exception as exc:  # noqa: BLE001
                reply_text = (
                    "Укажите тикер в сообщении (например «AMZN, прогноз на неделю»), "
                    "и я построю анализ на основе модели Quant Analytics."
                )
                logger.warning("Open chat reply failed", error=str(exc))

        advisor_msg = MessageORM(
            id=new_uuid(),
            conversation_id=conversation_id,
            sender_id=advisor_sender_id(),
            sender_role=MessageSenderRole.ADVISOR_AI.value,
            body=reply_text,
        )
        db.add(advisor_msg)
        await db.flush()
        return MessageRead.model_validate(user_msg), MessageRead.model_validate(advisor_msg)

    async def ask_ticker_ai(
        self,
        db: AsyncSession,
        conversation_id: str,
        *,
        identity: IdentityORM | None,
        user_id: str,
        system_role: SystemRole,
        body: MessageCreate,
    ) -> tuple[MessageRead, MessageRead]:
        conv = await self.get_conversation(
            db, conversation_id, identity=identity, user_id=user_id, system_role=system_role
        )
        if not conv.related_symbol:
            raise ValueError("Not a ticker conversation")
        return await self.ask_advisor(
            db,
            conversation_id,
            identity=identity,
            user_id=user_id,
            system_role=system_role,
            body=body,
        )

    async def _can_access(
        self,
        db: AsyncSession,
        conv: ConversationORM,
        *,
        identity: IdentityORM | None,
        user_id: str,
        system_role: SystemRole,
    ) -> bool:
        if system_role == SystemRole.USER:
            return conv.client_profile_id == user_id
        if has_permission(system_role, "*"):
            return True
        if system_role == SystemRole.OPERATOR_ADMIN and has_permission(system_role, "chat.read"):
            admin_id = identity.id if identity else None
            return conv.assigned_admin_id in (None, admin_id)
        return False


chat_service = ChatService()
