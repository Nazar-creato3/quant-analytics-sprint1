export { GENERATED_APP_ROUTES } from "./generatedRoutes";

export type TourAudience = "everyone" | "staff" | "admin";

export type TourStep = {
  id: string;
  title: string;
  body: string;
  hint?: string;
  /** Matches `[data-tour="…"]`. Empty = centered card, no spotlight. */
  target?: string;
  audience?: TourAudience;
};

/** First-login walkthrough. Observation only — nothing is required. */
export const FIRST_LOGIN_TOUR: TourStep[] = [
  {
    id: "welcome",
    title: "Quant Analytics",
    body: "Рабочий стол для прогноза, риска и исполнения. Это короткий экскурс по разделам — можно закрыть в любой момент и пользоваться платформой сразу.",
    hint: "Ни один шаг не требует нажатий в интерфейсе. Дальше только рассказ, что где лежит.",
  },
  {
    id: "equity",
    title: "Счёт и лимит",
    target: "nav-equity",
    body: "Справа в шапке — кап (сколько можно торговать), баланс по площадкам и сумма в открытых позициях. Это первое место, куда смотреть после входа.",
    hint: "Цифры обновляются по клику на сам блок. Ключи площадок настраиваются позже в Настройках и Кабинете.",
  },
  {
    id: "dashboard",
    title: "Dashboard",
    target: "dashboard-desk",
    body: "Главный экран оператора: вотчлист, график, лента решений и новости. Здесь видно, что система предлагает и что уже в работе — без перехода в другие разделы.",
  },
  {
    id: "direct-deals",
    title: "Direct Deals",
    target: "nav-direct-deals",
    body: "Ручные сделки и согласование исполнения. Сюда идут, когда нужна конкретная сделка, а не бот.",
  },
  {
    id: "bots",
    title: "Bots",
    target: "nav-bots",
    body: "Сетка, DCA и импульсные боты. Раздел про автоматические правила на крипто и других площадках, не про прогноз как таковой.",
  },
  {
    id: "forecast",
    title: "Forecast",
    target: "nav-forecasting",
    body: "Оценки относительно бенчмарка, сценарии и факторы по тикеру. Модели переобучаются на сервере по расписанию — отдельной кнопки «тренировать» на этом экране нет.",
  },
  {
    id: "chat",
    title: "AI Chat",
    target: "nav-chat",
    body: "Разбор тикера и контекста рынка текстом. Это советник поверх тех же данных, не отдельный брокер.",
  },
  {
    id: "risk",
    title: "Risk",
    target: "nav-portfolio-risk",
    body: "Концентрация, лимиты и портфельный риск. Имеет смысл открыть до того, как увеличивать размер позиций.",
  },
  {
    id: "settings",
    title: "Настройки и Кабинет",
    target: "nav-settings",
    body: "Вотчлист, пороги риска, тема. В Кабинете — профиль и торговые счета. На узком экране оба пункта могут быть в меню «Ещё».",
    hint: "Экскурс можно открыть снова из Настроек — блок «Знакомство с платформой».",
  },
  {
    id: "more",
    title: "Остальное меню",
    target: "nav-more",
    body: "Screener, конструктор стратегий и служебные разделы живут рядом с основными пунктами. На широком мониторе они в строке, на обычном — за «Ещё».",
  },
];

export function stepsForAudience(isStaff: boolean, isAdmin: boolean): TourStep[] {
  return FIRST_LOGIN_TOUR.filter((step) => {
    if (!step.audience || step.audience === "everyone") return true;
    if (step.audience === "admin") return isAdmin;
    if (step.audience === "staff") return isStaff || isAdmin;
    return true;
  });
}
