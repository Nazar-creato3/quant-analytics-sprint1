import { analyticsNote, trackBody } from "@/lib/product-analytics";

export function AnalyticsNote() {
  const dropped = trackBody({
    name: "user_return",
    subject: "site",
    properties: {},
    consent: false,
    doNotTrack: true,
  });
  return (
    <p className="mt-4 text-sm text-qa-muted" data-analytics-status={dropped.do_not_track ? "dnt" : "open"}>
      {analyticsNote()} Включённый режим «не отслеживать» отбрасывает запись.
    </p>
  );
}
