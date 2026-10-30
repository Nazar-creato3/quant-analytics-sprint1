"use client";

import { useState } from "react";
import { lane2Post } from "@/lib/lane2-fetch";
import { supportLines } from "@/lib/support-desk";

export function SupportReportCard() {
  const lines = supportLines();
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState("нет данных");
  return (
    <section aria-labelledby="support-title" className="rounded-xl border border-qa-border p-3 text-sm">
      <h1 id="support-title" className="font-medium">
        {lines[0]}
      </h1>
      {lines.slice(1).map((line) => (
        <p key={line} className="mt-1 text-xs text-qa-muted">
          {line}
        </p>
      ))}
      <form
        className="mt-3"
        onSubmit={(event) => {
          event.preventDefault();
          void lane2Post("/support/report", {
            page: typeof window === "undefined" ? "" : window.location.pathname,
            version: "local",
            request_id: "ui",
            errors: [],
            description,
            screenshot_consent: false,
          }).then((row) => setStatus(String(row.status ?? row.reason ?? "нет данных")));
        }}
      >
        <label className="block text-sm">
          Описание
          <textarea
            name="description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            className="mt-1 block w-full border border-neutral-300 p-1"
          />
        </label>
        <button type="submit" className="mt-2 border border-neutral-300 px-2 py-1">
          Отправить
        </button>
      </form>
      <p className="mt-2 text-xs text-qa-muted">Статус обращения: {status}</p>
    </section>
  );
}
