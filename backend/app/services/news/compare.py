"""Compare dictionary vs bag-of-words NB on the labeled news set (Prompt 44)."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from app.services.news.labeled import labeled_news
from app.services.news.pipeline import classify_news_event, link_tickers, sentiment_lexicon

_LABELS = ("dividend", "earnings", "sanctions", "cbr", "m_and_a", "guidance", "other")


def _tokens(text: str) -> list[str]:
    return [t for t in text.lower().replace(",", " ").split() if len(t) > 2]


def _f1(y_true: list[str], y_pred: list[str], labels: tuple[str, ...]) -> float:
    scores: list[float] = []
    for lab in labels:
        tp = sum(1 for a, b in zip(y_true, y_pred) if a == lab and b == lab)
        fp = sum(1 for a, b in zip(y_true, y_pred) if a != lab and b == lab)
        fn = sum(1 for a, b in zip(y_true, y_pred) if a == lab and b != lab)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        scores.append(0.0 if prec + rec == 0 else 2 * prec * rec / (prec + rec))
    return sum(scores) / len(scores) if scores else 0.0


def _nb_predict(train: list[dict[str, Any]], test: list[dict[str, Any]]) -> list[str]:
    docs: dict[str, Counter[str]] = defaultdict(Counter)
    prior: Counter[str] = Counter()
    vocab: set[str] = set()
    for row in train:
        lab = row["event"]
        prior[lab] += 1
        toks = _tokens(row["title"])
        docs[lab].update(toks)
        vocab.update(toks)
    v = max(len(vocab), 1)
    out: list[str] = []
    n = sum(prior.values()) or 1
    for row in test:
        toks = _tokens(row["title"])
        best, best_s = "other", float("-inf")
        for lab in _LABELS:
            if prior[lab] == 0:
                continue
            logp = prior[lab] / n
            total = sum(docs[lab].values()) + v
            score = logp
            for t in toks:
                score *= (docs[lab][t] + 1) / total
            if score > best_s:
                best, best_s = lab, score
        out.append(best)
    return out


def compare_event_models(*, n: int = 500, holdout: float = 0.2) -> dict[str, Any]:
    rows = labeled_news(n)
    cut = int(len(rows) * (1 - holdout))
    train, test = rows[:cut], rows[cut:]
    y = [r["event"] for r in test]
    dict_pred = [classify_news_event(r["title"]) for r in test]
    nb_pred = _nb_predict(train, test)
    dict_f1 = _f1(y, dict_pred, _LABELS)
    nb_f1 = _f1(y, nb_pred, _LABELS)
    chosen = "dictionary" if dict_f1 >= nb_f1 else "naive_bayes"
    ticker_hits = 0
    for row in test:
        linked = link_tickers(row["title"])
        if row["ticker"] in linked:
            ticker_hits += 1
    return {
        "n": n,
        "test": len(test),
        "dictionary_f1": round(dict_f1, 4),
        "naive_bayes_f1": round(nb_f1, 4),
        "transformer_f1": None,
        "llm_f1": None,
        "chosen": chosen,
        "ticker_link_accuracy": round(ticker_hits / len(test), 4) if test else 0.0,
        "sentiment_agree": round(
            sum(1 for r in test if sentiment_lexicon(r["title"]) == r["sentiment"]) / len(test),
            4,
        )
        if test
        else 0.0,
    }
