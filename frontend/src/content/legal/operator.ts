/**
 * Owner of the site and the address for legally significant messages
 * (149-FZ art. 10.2-2; 152-FZ art. 18.1). One place for every page.
 *
 * The mailbox is on the service's own domain at a Russian mail provider
 * (lawyer decision L-05: A) — not Gmail, which would be a cross-border transfer.
 * OGRNIP is shown once filled in.
 */
export const OPERATOR = {
  name: "Индивидуальный предприниматель Коваленко Назар Антонович",
  shortName: "ИП Коваленко Н. А.",
  inn: "971516322732",
  ogrnip: process.env.NEXT_PUBLIC_OPERATOR_OGRNIP || "",
  email: process.env.NEXT_PUBLIC_LEGAL_EMAIL || "support@quantanalyticsclub.ru",
  site: "quantanalyticsclub.ru",
} as const;

export function operatorLine(): string {
  const parts = [OPERATOR.shortName, `ИНН ${OPERATOR.inn}`];
  if (OPERATOR.ogrnip) parts.push(`ОГРНИП ${OPERATOR.ogrnip}`);
  return parts.join(", ");
}
