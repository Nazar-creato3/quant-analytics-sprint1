export type StatusLevel = "ok" | "caution" | "block" | "none";

export type ReasonCode =
  | "no-data"
  | "pipeline-off"
  | "permissions"
  | "error"
  | "loading"
  | "no-symbol";

export interface ReasonStateProps {
  code: ReasonCode;
  title: string;
  detail?: string;
  action?: React.ReactNode;
}

export interface FeedEvent {
  id: string;
  ts: string;
  type: "signal" | "risk" | "execution" | "system";
  level: StatusLevel;
  title: string;
  detail?: string;
  maneuverId?: string;
  maneuverStatus?: string;
  dealIntentId?: string;
}
