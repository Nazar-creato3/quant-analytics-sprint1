/** Copy and API shape for TWR vs MWR (Prompt 08). */

export type PortfolioReturns = {
  twr: string;
  mwr: string;
  twr_label: string;
  mwr_label: string;
  incomplete: boolean;
  load_report_hint: string | null;
};

export function explainTwrs(): string {
  return "TWR — результат решений без пополнений и выводов. MWR — как росли ваши деньги с учётом потоков.";
}

export type SimpleAltSleeve = {
  ticker: string;
  label?: string;
  data_status?: string;
  reason?: string | null;
  end_value?: string | null;
  twr?: string | null;
  mwr?: string | null;
  diff_value?: string | null;
  diff_twr_pp?: string | null;
  diff_mwr_pp?: string | null;
  source?: string | null;
  price_as_of?: string | null;
};

export type SimpleAltResponse = {
  data_status?: string;
  reason?: string | null;
  as_of?: string;
  portfolio?: PortfolioReturns & { end_value?: string | null };
  alternatives?: SimpleAltSleeve[];
};