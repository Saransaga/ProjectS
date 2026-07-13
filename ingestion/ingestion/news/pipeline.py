"""Single entry point each source job calls per raw item, so job code only
has to build the raw fields (headline/summary/url/...) and hand the text off
here for ticker tagging + sentiment + urgency/relevance scoring."""

from . import classify, sentiment
from .ticker_matching import match_tickers


def enrich(headline: str, summary: str | None, source_type: str, alias_index) -> dict:
    text = f"{headline}. {summary or ''}"
    ticker_ids = match_tickers(text, alias_index)
    sentiment_label, sentiment_score = sentiment.score(text)

    return {
        "ticker_ids": ticker_ids,
        "sentiment_label": sentiment_label,
        "sentiment_score": sentiment_score,
        "urgency": classify.classify_urgency(text),
        "relevance_score": classify.compute_relevance(bool(ticker_ids), source_type),
        "source_credibility_weight": classify.credibility_weight(source_type),
    }
