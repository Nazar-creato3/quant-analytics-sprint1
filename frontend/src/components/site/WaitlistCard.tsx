"use client";

import { useEffect, useState } from "react";
import { lane2Get } from "@/lib/lane2-fetch";
import { waitlistLines } from "@/lib/waitlist";

export function WaitlistCard() {
  const lines = waitlistLines();
  const [offer, setOffer] = useState("нет данных");
  useEffect(() => {
    void lane2Get("/waitlist/offer").then((row) => {
      setOffer(String(row.consent ?? "нет данных"));
    });
  }, []);
  return (
    <section aria-labelledby="waitlist-title" className="mt-4 rounded-xl border border-neutral-300 bg-white p-3 text-sm text-neutral-800">
      <h2 id="waitlist-title" className="font-medium">
        {lines[0]}
      </h2>
      <p className="mt-1 text-sm text-neutral-700">{lines[1]}</p>
      <p className="mt-1 text-sm text-neutral-700">{lines[2]}</p>
      <p className="mt-1 text-sm text-neutral-700">Статус оферты: {offer}</p>
      <form>
        <label className="mt-2 block text-sm">
          Почта
          <input aria-label="Почта" name="email" type="email" disabled className="mt-1 block w-full border border-neutral-300 p-1" />
        </label>
        <label className="mt-2 block text-sm">
          Имя
          <input aria-label="Имя" name="name" type="text" disabled className="mt-1 block w-full border border-neutral-300 p-1" />
        </label>
        <input className="hidden" name="company_website" tabIndex={-1} autoComplete="off" aria-hidden="true" />
        <button type="button" disabled className="mt-2 border border-neutral-300 px-2 py-1">
          {lines[3]}
        </button>
      </form>
      <p className="mt-1 text-sm text-neutral-700">{lines[4]}</p>
    </section>
  );
}
