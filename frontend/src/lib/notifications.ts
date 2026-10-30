/** Notification center types (Prompt 07). BOT_RISK maps to bot.circuit_breaker. */

export type NotificationItem = {
  id: number
  event_name: string
  text: string
  read: boolean
  created_at: string
}

export function criticalBanner(eventName: string): string | null {
  if (eventName === "bot.circuit_breaker" || eventName === "BOT_RISK") {
    return "Автоматическая защита остановила ботов"
  }
  if (eventName === "risk.limit_breached") {
    return "Превышен лимит риска"
  }
  return null
}
