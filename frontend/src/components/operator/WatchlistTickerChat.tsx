"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Send, X } from "lucide-react";
import { toast } from "react-hot-toast";
import { MessengerBubble } from "@/components/chat/MessengerBubble";
import { chatApi } from "@/lib/api";
import { extractErrorMessage } from "@/lib/errors";
import { useChatWebSocket } from "@/hooks/useWebSocket";
import { Spinner } from "@/components/ui";

interface WatchlistTickerChatProps {
  symbol: string;
  onClose: () => void;
}

interface ChatMessage {
  id: string;
  sender_role: string;
  body: string;
  created_at?: string;
}

interface Conversation {
  id: string;
  related_symbol?: string | null;
}

function normalizeSymbol(symbol: string): string {
  return symbol.trim().toUpperCase();
}

function conversationMatchesSymbol(conversation: Conversation | undefined, symbol: string): boolean {
  if (!conversation?.id) return false;
  return normalizeSymbol(conversation.related_symbol ?? "") === symbol;
}

export function WatchlistTickerChat({ symbol, onClose }: WatchlistTickerChatProps) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const normalizedSymbol = useMemo(() => normalizeSymbol(symbol), [symbol]);

  const convQ = useQuery({
    queryKey: ["watchlist-chat-conv", normalizedSymbol],
    queryFn: () => chatApi.forTicker(normalizedSymbol),
    staleTime: 60_000,
  });

  const conversation = convQ.data as Conversation | undefined;
  const conversationReady =
    conversationMatchesSymbol(conversation, normalizedSymbol) && !convQ.isFetching;
  const conversationId = conversationReady ? conversation!.id : undefined;

  const messagesQ = useQuery({
    queryKey: ["watchlist-chat-messages", normalizedSymbol, conversationId],
    queryFn: () => chatApi.getMessages(conversationId!),
    enabled: conversationReady,
  });

  useChatWebSocket(conversationId ?? null, () => {
    if (conversationId) {
      queryClient.invalidateQueries({
        queryKey: ["watchlist-chat-messages", normalizedSymbol, conversationId],
      });
    }
  });

  const sendMut = useMutation({
    mutationFn: (body: string) => chatApi.askAdvisor(conversationId!, body),
    onSuccess: () => {
      setDraft("");
      queryClient.invalidateQueries({
        queryKey: ["watchlist-chat-messages", normalizedSymbol, conversationId],
      });
    },
    onError: (e) => toast.error(extractErrorMessage(e, "Не удалось отправить сообщение")),
  });

  const newChatMut = useMutation({
    mutationFn: async () => {
      if (conversationId) {
        await chatApi.archiveConversation(conversationId);
      }
      return chatApi.forTicker(normalizedSymbol);
    },
    onSuccess: () => {
      setDraft("");
      queryClient.invalidateQueries({ queryKey: ["watchlist-chat-conv", normalizedSymbol] });
      queryClient.invalidateQueries({ queryKey: ["watchlist-chat-messages"] });
      toast.success("Новый чат по тикеру");
    },
    onError: (e) => toast.error(extractErrorMessage(e, "Не удалось начать новый чат")),
  });

  const messages = conversationReady ? ((messagesQ.data?.items ?? []) as ChatMessage[]) : [];

  useEffect(() => {
    setDraft("");
  }, [normalizedSymbol]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, sendMut.isPending]);

  const inputDisabled = !conversationReady || convQ.isError || convQ.isLoading || convQ.isFetching;

  return (
    <div className="border-t border-cockpit-border flex flex-col flex-1 min-h-[200px] shrink-0 bg-cockpit-panel/40">
      <div className="flex items-center justify-between px-2 py-1.5 border-b border-cockpit-border/60 shrink-0">
        <div className="flex items-center gap-1.5 min-w-0">
          <Bot size={12} className="text-terminal-accent shrink-0" />
          <span className="text-[10px] font-semibold text-terminal-accent truncate">
            Чат · {normalizedSymbol}
          </span>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            type="button"
            className="text-[9px] px-1.5 py-0.5 rounded border border-cockpit-border text-qa-muted hover:text-qa-text"
            disabled={newChatMut.isPending || !conversationReady}
            onClick={() => newChatMut.mutate()}
            title="Новый чат (сброс контекста)"
          >
            {newChatMut.isPending ? "…" : "Новый"}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="p-0.5 rounded text-qa-muted hover:text-qa-text"
            title="Закрыть чат"
          >
            <X size={12} />
          </button>
        </div>
      </div>

      <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto p-2 space-y-1.5 bg-qa-bg/30">
        {convQ.isLoading || convQ.isFetching || messagesQ.isLoading ? (
          <div className="flex justify-center py-4">
            <Spinner size={16} />
          </div>
        ) : messages.length === 0 ? (
          <p className="text-qa-muted text-center py-3 leading-relaxed text-[10px]">
            Спросите про {normalizedSymbol}: «почему такой score?», «какой риск?», «события по тикеру»
          </p>
        ) : (
          messages.map((m) => (
            <MessengerBubble
              key={m.id}
              senderRole={m.sender_role}
              body={m.body}
              compact
            />
          ))
        )}
        {sendMut.isPending && (
          <div className="flex justify-start">
            <div className="text-terminal-accent/80 italic px-2 py-1 text-[10px] animate-pulse rounded-2xl bg-qa-panel-secondary/80">
              Проводится глубокий анализ данных…
            </div>
          </div>
        )}
      </div>

      <form
        className="p-2 border-t border-cockpit-border/60 flex gap-1 shrink-0 bg-cockpit-panel/95"
        onSubmit={(e) => {
          e.preventDefault();
          if (!draft.trim() || !conversationId || sendMut.isPending) return;
          sendMut.mutate(draft.trim());
        }}
      >
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={
            convQ.isLoading || convQ.isFetching
              ? "Подключение к чату…"
              : convQ.isError
                ? "Чат недоступен"
                : "Вопрос по тикеру…"
          }
          disabled={inputDisabled}
          aria-disabled={inputDisabled}
          className="flex-1 min-w-0 bg-cockpit-bg border border-cockpit-border rounded px-2 py-1.5 text-[10px] text-qa-text placeholder:text-qa-muted focus:outline-none focus:border-terminal-accent/50 disabled:opacity-60 disabled:cursor-not-allowed"
        />
        <button
          type="submit"
          disabled={!draft.trim() || !conversationId || sendMut.isPending}
          className="p-1.5 rounded bg-terminal-accent text-terminal-bg disabled:opacity-40 hover:bg-terminal-accent-dim shrink-0"
          title="Отправить"
        >
          <Send size={11} />
        </button>
      </form>
      <p className="px-2 pb-1 text-[9px] text-qa-muted shrink-0">
        Аналитическая справка, не инвестиционная рекомендация.
      </p>
    </div>
  );
}
