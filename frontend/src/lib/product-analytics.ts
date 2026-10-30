import { lane2Post } from "@/lib/lane2-fetch";

export type TrackBody = {
  name: string;
  subject: string;
  properties: Record<string, string>;
  consent: boolean;
  do_not_track: boolean;
};

const CLIENT_EVENTS = new Set([
  "first_report_shown",
  "risk_view",
  "maneuver_viewed",
  "maneuver_edited",
  "profile_questionnaire_completed",
  "user_return",
]);

function sessionSubject(): string {
  const key = "qa-lane2-subject";
  const existing = sessionStorage.getItem(key);
  if (existing && !existing.includes("@")) return existing;
  const next = `s${Math.random().toString(36).slice(2, 12)}`;
  sessionStorage.setItem(key, next);
  return next;
}

export function trackBody(input: {
  name: string;
  subject: string;
  properties: Record<string, string>;
  consent: boolean;
  doNotTrack: boolean;
}): TrackBody {
  return {
    name: input.name,
    subject: input.subject,
    properties: input.properties,
    consent: input.consent,
    do_not_track: input.doNotTrack,
  };
}

export function analyticsNote(): string {
  return "Сбор событий выключен: текст согласия нет данных. Согласие ожидает текста. Третьим сторонам данные не передаются.";
}

export async function trackClientEvent(
  name: string,
  properties: Record<string, string> = {},
): Promise<Record<string, unknown>> {
  if (typeof window === "undefined") return { status: "нет данных" };
  if (!CLIENT_EVENTS.has(name)) return { status: "rejected", reason: "schema" };
  if (Object.keys(properties).some((key) => key === "email" || key === "name" || key === "token")) {
    return { status: "rejected", reason: "schema" };
  }
  const dnt = navigator.doNotTrack === "1";
  return lane2Post(
    "/analytics/events",
    trackBody({
      name,
      subject: sessionSubject(),
      properties,
      consent: false,
      doNotTrack: dnt,
    }),
  );
}
