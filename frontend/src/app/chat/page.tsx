"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "react-hot-toast";
import { NavBar } from "@/components/layout/NavBar";
import { AppPageShell } from "@/components/layout/AppPageShell";
import { MessengerBubble } from "@/components/chat/MessengerBubble";
import { chatApi } from "@/lib/api";
import { useChatWebSocket } from "@/hooks/useWebSocket";
import { extractErrorMessage } from "@/lib/errors";

interface Conversation {
  id: string;
  title?: string | null;
  related_symbol?: string | null;
  related_deal_intent_id?: string | null;
  status: string;
}

function normalizeSymbol(symbol: string | null | undefined): string | null {
  if (!symbol?.trim()) return null;
  return symbol.trim().toUpperCase();
}

function conversationLabel(c: Conversation): string {
  if (c.title?.trim()) return c.title.trim();
  if (c.related_symbol?.trim()) return c.related_symbol.trim();
  if (c.related_deal_intent_id) return `Deal ${c.related_deal_intent_id.slice(0, 8)}…`;
  return `${c.id.slice(0, 8)}…`;
}

export default function ChatPage() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const symbolParam = normalizeSymbol(searchParams.get("symbol"));
  const dealIntentParam = searchParams.get("deal_intent")?.trim() || null;

  const [activeId, setActiveId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const tickerConvQ = useQuery({
    queryKey: ["chat-ticker-conv", symbolParam],
    queryFn: () => chatApi.forTicker(symbolParam!),
    enabled: !!symbolParam,
  });

  const dealConvQ = useQuery({
    queryKey: ["chat-deal-conv", dealIntentParam],
    queryFn: () => chatApi.forDealIntent(dealIntentParam!),
    enabled: !!dealIntentParam && !symbolParam,
  });

  useEffect(() => {
    const scopedId = symbolParam
      ? (tickerConvQ.data?.id as string | undefined)
      : dealIntentParam
        ? (dealConvQ.data?.id as string | undefined)
        : undefined;
    if (scopedId) {
      setActiveId(scopedId);
    }
  }, [symbolParam, dealIntentParam, tickerConvQ.data?.id, dealConvQ.data?.id]);

  const convQ = useQuery({
    queryKey: ["chat-conversations", symbolParam ?? "all"],
    queryFn: () =>
      chatApi.listConversations(
        symbolParam ? { related_symbol: symbolParam } : undefined,
      ),
  });

  const conversations = (convQ.data?.items ?? []) as Conversation[];
  const activeConversation = useMemo(
    () => conversations.find((c) => c.id === activeId),
    [conversations, activeId],
  );

  const activeSymbol = normalizeSymbol(activeConversation?.related_symbol);
  const conversationReady =
    !!activeId &&
    (!symbolParam || activeSymbol === symbolParam) &&
    (!dealIntentParam || activeConversation?.related_deal_intent_id === dealIntentParam);

  const messagesQ = useQuery({
    queryKey: ["chat-messages", activeId, activeSymbol ?? "", dealIntentParam ?? ""],
    queryFn: () => chatApi.getMessages(activeId!),
    enabled: conversationReady,
  });

  useChatWebSocket(conversationReady ? activeId : null, () => {
    if (activeId) {
      queryClient.invalidateQueries({
        queryKey: ["chat-messages", activeId, activeSymbol ?? "", dealIntentParam ?? ""],
      });
    }
  });

  const sendMut = useMutation({
    mutationFn: (body: string) => chatApi.askAdvisor(activeId!, body),
    onSuccess: () => {
      setDraft("");
      queryClient.invalidateQueries({
        queryKey: ["chat-messages", activeId, activeSymbol ?? "", dealIntentParam ?? ""],
      });
      queryClient.invalidateQueries({ queryKey: ["chat-conversations"] });
    },
    onError: (e) => toast.error(extractErrorMessage(e, "Не удалось получить ответ советника")),
  });

  const newChatMut = useMutation({
    mutationFn: async () => {
      if (activeId) {
        await chatApi.archiveConversation(activeId);
      }
      if (symbolParam) {
        return chatApi.forTicker(symbolParam);
      }
      if (dealIntentParam) {
        return chatApi.forDealIntent(dealIntentParam);
      }
      return chatApi.createConversation({});
    },
    onSuccess: (conv: { id: string }) => {
      setDraft("");
      setActiveId(conv.id);
      queryClient.invalidateQueries({ queryKey: ["chat-conversations"] });
      queryClient.invalidateQueries({ queryKey: ["chat-ticker-conv", symbolParam] });
      queryClient.invalidateQueries({ queryKey: ["chat-deal-conv", dealIntentParam] });
      queryClient.invalidateQueries({ queryKey: ["chat-messages"] });
      toast.success("Новый диалог начат");
    },
    onError: (e) => toast.error(extractErrorMessage(e, "Не удалось начать новый диалог")),
  });

  const sidebarConversations = useMemo(() => {
    if (symbolParam) {
      return conversations.filter(
        (c) => normalizeSymbol(c.related_symbol) === symbolParam,
      );
    }
    return conversations;
  }, [conversations, symbolParam]);

  const messages = conversationReady ? (messagesQ.data?.items ?? []) : [];
  const loadingThread =
    (!!symbolParam && (tickerConvQ.isLoading || tickerConvQ.isFetching)) ||
    (!!dealIntentParam && !symbolParam && (dealConvQ.isLoading || dealConvQ.isFetching)) ||
    (!!activeId && messagesQ.isLoading);

  return (
    <div className="h-[calc(100dvh-3.5rem)] md:h-[calc(100dvh-3.5rem)] overflow-hidden bg-cockpit-bg text-qa-text flex flex-col operator-shell">
      <NavBar activeTab="chat" />
      <AppPageShell
        title={symbolParam ? `Сообщения · ${symbolParam}` : "Сообщения"}
        description="Диалоги с советником по тикерам и сделкам"
        width="lg"
        fillViewport
        className="pb-2 md:pb-4"
      >
        <div className="flex-1 grid grid-cols-1 md:grid-cols-[minmax(220px,260px)_1fr] gap-4 min-h-0 h-full">
        <aside className="cockpit-panel flex flex-col min-h-0 overflow-hidden max-h-[35vh] md:max-h-none">
          <div className="px-3 py-2 border-b border-cockpit-border shrink-0 flex items-center justify-between gap-2">
            <span className="text-xs font-semibold text-qa-muted uppercase tracking-wide">Диалоги</span>
            <button
              type="button"
              className="btn-secondary text-[10px] px-2 py-1 shrink-0"
              disabled={newChatMut.isPending}
              onClick={() => newChatMut.mutate()}
              title="Начать новый диалог (контекст сбрасывается на сервере)"
            >
              {newChatMut.isPending ? "…" : "+ Новый чат"}
            </button>
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-2">
          {sidebarConversations.length === 0 && (
            <p className="text-xs text-qa-muted">Нет активных диалогов.</p>
          )}
          {sidebarConversations.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => setActiveId(c.id)}
              className={`w-full text-left text-xs px-2 py-2.5 min-h-[44px] rounded border ${
                activeId === c.id
                  ? "border-terminal-accent bg-[var(--qa-active)]"
                  : "border-cockpit-border hover:bg-cockpit-panel-raised/40"
              }`}
            >
              <div className="truncate font-medium">{conversationLabel(c)}</div>
              <div className="text-qa-muted">{c.status}</div>
            </button>
          ))}
          </div>
        </aside>

        <section className="cockpit-panel flex flex-col flex-1 min-h-[280px] md:min-h-0 overflow-hidden">
          {!activeId ? (
            <div className="flex-1 flex items-center justify-center text-sm text-qa-muted">
              Выберите диалог или{" "}
              <Link href="/cockpit/SPY" className="text-terminal-accent ml-1 hover:underline">
                обсудите рекомендацию
              </Link>
            </div>
          ) : (
            <>
              {activeConversation && (
                <div className="px-3 py-2 border-b border-cockpit-border flex items-center justify-between gap-2 min-w-0">
                  <div className="text-sm font-medium truncate min-w-0">
                    {conversationLabel(activeConversation)}
                  </div>
                  <button
                    type="button"
                    className="btn-secondary text-[10px] px-2 py-1 shrink-0"
                    disabled={newChatMut.isPending || !conversationReady}
                    onClick={() => newChatMut.mutate()}
                  >
                    Новый чат
                  </button>
                </div>
              )}
              <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-2 bg-qa-bg/40">
                {loadingThread ? (
                  <p className="text-xs text-qa-muted italic text-center">Загрузка диалога…</p>
                ) : (
                  messages.map((m: { id: string; sender_role: string; body: string }) => (
                    <MessengerBubble key={m.id} senderRole={m.sender_role} body={m.body} />
                  ))
                )}
                {sendMut.isPending && (
                  <div className="flex justify-start">
                    <p className="text-xs text-terminal-accent/80 italic px-3 py-2 rounded-2xl bg-qa-panel-secondary/80 animate-pulse">
                      Проводится глубокий анализ данных…
                    </p>
                  </div>
                )}
              </div>
              <form
                className="border-t border-cockpit-border p-3 flex gap-2 shrink-0"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!draft.trim() || sendMut.isPending || !conversationReady) return;
                  sendMut.mutate(draft.trim());
                }}
              >
                <input
                  className="input flex-1 text-sm min-w-0"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder={
                    activeSymbol
                      ? `Сообщение по ${activeSymbol}… (напр. «почему такой score?»)`
                      : "Сообщение советнику… (укажите тикер, напр. AMZN)"
                  }
                  disabled={sendMut.isPending || !conversationReady}
                />
                <button
                  type="submit"
                  className="btn-primary text-xs shrink-0"
                  disabled={sendMut.isPending || !conversationReady}
                >
                  Отправить
                </button>
              </form>
              <p className="px-3 pb-2 text-[9px] text-qa-muted shrink-0">
                Аналитическая справка, не инвестиционная рекомендация.
              </p>
            </>
          )}
        </section>
        </div>
      </AppPageShell>
    </div>
  );
}
