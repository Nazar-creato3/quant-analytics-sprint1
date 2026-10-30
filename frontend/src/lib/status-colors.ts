/** Terminal-aligned status badge colors — use with `badge` or inline `clsx`. */
export const STATUS_BADGE_COLORS: Record<string, string> = {
  pending: "text-terminal-accent badge-accent",
  pending_approval: "text-terminal-accent badge-accent",
  awaiting_approval: "text-terminal-accent badge-accent",
  approved: "text-terminal-up badge-success",
  rejected: "text-terminal-down badge-danger",
  executing: "text-terminal-accent badge-accent",
  filled: "text-terminal-up badge-success",
  cancelled: "text-qa-muted bg-qa-panel-secondary border-qa-border",
  invalidated: "text-terminal-accent badge-accent",
};
