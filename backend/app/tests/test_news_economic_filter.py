from app.services.news.filtering import is_economic_news


def test_general_agency_needs_market_topic() -> None:
    assert not is_economic_news("Зенит обыграл Динамо и вернулся на первое место в РПЛ", source="interfax")
    assert not is_economic_news("Восемь человек пострадали в ДТП с рейсовым автобусом", source="interfax")
    assert not is_economic_news("Минобороны заявило об уничтожении 38 беспилотников", source="interfax")
    assert is_economic_news("ЦБ сохранил ключевую ставку на уровне 14%", source="interfax")
    assert is_economic_news("Нефть дорожает на фоне атак на танкеры в Ормузском проливе — экспорт", source="interfax")


def test_financial_publishers_pass() -> None:
    assert is_economic_news("Musk says SpaceX raised $40 bln in debt", source="investing_com")
