"""QuantConnect research twin — paste into Algorithm Lab.

Paid/alt datasets (Spectral, Brain, Benzinga, Quiver, FINRA OTC, CFTC, …)
only exist on QuantConnect. The VPS uses FRED/Eurostat/news/factor caches instead.
Surveys are monthly: check Slice before indexing. History: use timedelta(days=1825), not 60 bars.
"""
from datetime import timedelta

from AlgorithmImports import *  # type: ignore


class ApexDeskQuantConnect(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2019, 1, 1)
        self.set_cash(100_000)
        self.universe_settings.resolution = Resolution.DAILY
        self.settings.automatic_indicator_warm_up = True
        self.settings.seed_initial_prices = True

        self._spy = self.add_equity("SPY", Resolution.DAILY).symbol
        self._universe = self.universe.etf("SPY")
        self.add_universe(self._universe)

        # Macro / surveys (unlinked — geo code, not a ticker)
        self._ff = self.add_data(FamaFrench, "FF", Resolution.DAILY).symbol
        self._esi_c = self.add_data(EurostatConsumerSurvey, Eurostat.Economies.GERMANY, Resolution.DAILY).symbol
        self._esi_i = self.add_data(EurostatIndustrySurvey, Eurostat.Economies.GERMANY, Resolution.DAILY).symbol
        self._esi_s = self.add_data(EurostatServicesSurvey, Eurostat.Economies.GERMANY, Resolution.DAILY).symbol
        self._hicp = self.add_data(EurostatConsumerPrices, Eurostat.Economies.EURO_AREA, Resolution.DAILY).symbol
        self._ip = self.add_data(EurostatIndustrialProduction, Eurostat.Economies.GERMANY, Resolution.DAILY).symbol
        self._fred = self.add_data(Fred, Fred.OECDRecessionIndicators.UNITED_STATES_FROM_PEAK_THROUGH_THE_TROUGH, Resolution.DAILY).symbol
        self._vixc = self.add_data(VIXCentralContango, "VX", Resolution.DAILY).symbol
        self._cpi = self.add_data(BLSEconomicSurveysCpi, "CPI").symbol
        self._ces = self.add_data(BLSEconomicSurveysCes, "CES").symbol
        self._cftc = self.add_data(CFTCFinancialFutures, CFTC.Markets.E_MINI_SP_500, Resolution.DAILY).symbol

        self._last_ff_mom = 0.0
        self._last_esi = 0.0
        self._last_contango = 0.0
        self._atr = {}
        self.schedule.on(self.date_rules.week_start("SPY"), self.time_rules.at(8, 0), self._rebalance)

    def on_securities_changed(self, changes):
        for sec in changes.added_securities:
            self._atr[sec.symbol] = self.atr(sec.symbol, 14, Resolution.DAILY)
            try:
                self.add_data(BrainSentimentIndicator7Day, sec.symbol)
            except Exception:
                pass
        for sec in changes.removed_securities:
            self._atr.pop(sec.symbol, None)

    def on_data(self, slice: Slice):
        ff = slice.get(FamaFrench)
        if self._ff in ff:
            mom = ff[self._ff].momentum
            if mom is not None:
                self._last_ff_mom = float(mom)
        cons = slice.get(EurostatConsumerSurvey)
        if self._esi_c in cons and cons[self._esi_c].consumer_confidence is not None:
            self._last_esi = float(cons[self._esi_c].consumer_confidence)
        vx = slice.get(VIXCentralContango)
        if self._vixc in vx:
            c = vx[self._vixc].contango_f_2_minus_f_1
            if c is not None:
                self._last_contango = float(c)

    def _rebalance(self):
        if self._last_esi < -20 or self._last_contango < -0.05:
            # Severe EU confidence dump / VIX backwardation: stay in SPY only.
            self.set_holdings(self._spy, 0.6)
            return
        symbols = list(self._universe.selected)
        scored = []
        for symbol in symbols:
            sec = self.securities[symbol]
            atr = self._atr.get(symbol)
            if atr is None or not atr.is_ready or sec.price <= 0:
                continue
            n = float(atr.current.value)
            atr_frac = n / float(sec.price)
            if atr_frac <= 0 or atr_frac > 0.06:
                continue
            fund = getattr(sec, "fundamentals", None)
            if fund is not None and hasattr(fund, "has_fundamental_data") and fund.has_fundamental_data:
                if getattr(fund, "market_cap", 0) and fund.market_cap < 2_000_000_000:
                    continue
            roc = float(sec.price / sec.close - 1.0) if sec.close else 0.0
            scored.append((symbol, 1.0 / atr_frac, roc))
        scored.sort(key=lambda t: t[2] + 0.1 * self._last_ff_mom)
        picked = scored[-8:]
        if not picked:
            return
        inv = [t[1] for t in picked]
        z = sum(inv) or 1.0
        gross = 0.85 if self._last_esi >= 0 else 0.65
        targets = [PortfolioTarget(t[0], min(0.18, gross * inv[i] / z)) for i, t in enumerate(picked)]
        self.set_holdings(targets, True)
        # Point-in-time history for surveys: years, not bar counts.
        _ = self.history(self._esi_c, timedelta(days=1825), Resolution.DAILY)
