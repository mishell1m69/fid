import time
import argparse
from difflib import SequenceMatcher
import hashlib
import html
import json
import logging
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import feedparser
import trafilatura

start = time.time()

DEFAULT_SOURCES_FILE = Path(__file__).with_name("sources.json")
DEFAULT_PREFERENCES_FILE = Path(__file__).with_name("preferences.json")
DEFAULT_OUTPUT_FILE = Path(__file__).with_name("articles.json")
USER_AGENT = "veille-personnalisee/1.0"
DEFAULT_MAX_PER_CATEGORY = 50
DEFAULT_MAX_AGE_DAYS = 10
TRACKING_PARAMETERS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_"}


class FeedLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.feed_links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "link":
            return
        attributes = dict(attrs)
        relation = attributes.get("rel", "").lower().split()
        content_type = attributes.get("type", "").lower()
        if "alternate" in relation and (
            "rss" in content_type or "atom" in content_type
        ):
            href = attributes.get("href")
            if href:
                self.feed_links.append(href)


def fetch_bytes(url):
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=20) as response:
        return response.read(), response.geturl(), response.headers.get_content_type()


def discover_feed_url(source_url):
    logging.info("Recherche du flux pour %s", source_url)
    content, final_url, content_type = fetch_bytes(source_url)
    parsed = feedparser.parse(content)
    if parsed.entries or parsed.feed.get("title"):
        return source_url, content

    if "html" not in content_type:
        raise ValueError("la reponse n'est ni un flux ni une page HTML")

    parser = FeedLinkParser()
    parser.feed(content.decode("utf-8", errors="replace"))
    for feed_link in parser.feed_links:
        candidate_url = urljoin(final_url, feed_link)
        feed_content, _, _ = fetch_bytes(candidate_url)
        candidate = feedparser.parse(feed_content)
        if candidate.entries or candidate.feed.get("title"):
            return candidate_url, feed_content

    raise ValueError("aucun flux RSS/Atom decouvert")


def clean_text(value):
    if not value:
        return ""
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def canonical_url(url):
    """Remove URL variations commonly introduced by tracking parameters."""
    parts = urlsplit(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMETERS and not key.lower().startswith("utm_")
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def article_id(url):
    return hashlib.sha256(canonical_url(url).encode("utf-8")).hexdigest()[:16]


def normalized_title(title):
    title = clean_text(title).lower()
    return re.sub(r"[^\w\s]", " ", title, flags=re.UNICODE)


def article_similarity(first, second):
    first_title = normalized_title(first["title"])
    second_title = normalized_title(second["title"])
    return SequenceMatcher(None, first_title, second_title).ratio()


def entry_date(entry):
    parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed_time:
        return datetime(*parsed_time[:6], tzinfo=timezone.utc).isoformat()
    return clean_text(entry.get("published") or entry.get("updated"))


def extract_article(entry):
    article_url = entry.get("link", "")
    if not article_url:
        return ""
    try:
        logging.debug("Extraction de %s", article_url)
        html = trafilatura.fetch_url(article_url)
        return clean_text(trafilatura.extract(html, include_comments=False)) if html else ""
    except Exception as error:
        logging.warning("Extraction impossible pour %s: %s", article_url, error)
        return ""


def normalize_entry(entry, source, feed_url, extract_content=True):
    description = entry.get("summary") or entry.get("description") or ""
    content = entry.get("content", [{}])
    if content and isinstance(content, list):
        description = content[0].get("value", description)
    return {
        "article_id": article_id(entry.get("link", "")),
        "title": clean_text(entry.get("title")),
        "url": entry.get("link", ""),
        "published": entry_date(entry),
        "description": clean_text(description),
        "content": extract_article(entry) if extract_content else "",
        "source": source["nom"],
        "category": source["categorie"],
        "feed_url": feed_url,
        "keywords": source.get("mots_cles", []),
        "excluded_keywords": source.get("mots_cles_exclus", []),
    }


def collect_sources(sources, extract_content=True):
    articles = []
    for source in sources:
        try:
            feed_url, feed_content = discover_feed_url(source["url"])
            feed = feedparser.parse(feed_content)
            logging.info("%s: %d article(s)", source["nom"], len(feed.entries))
            for entry in feed.entries:
                article = normalize_entry(entry, source, feed_url, extract_content)
                if article["title"] and article["url"]:
                    articles.append(article)
        except Exception as error:
            logging.warning("Source ignoree %s: %s", source["nom"], error)
    return articles


def load_preferences(preferences_file):
    with preferences_file.open(encoding="utf-8") as file:
        preferences = json.load(file)
    if not isinstance(preferences, dict):
        raise ValueError("le profil de preferences doit etre un objet JSON")
    categories = preferences.get("categories", {})
    if not isinstance(categories, dict):
        raise ValueError("le champ categories du profil doit etre un objet JSON")
    return preferences


def preference_context(preferences, category):
    """Return the profile context needed later by the AI evaluator."""
    return {
        "profile": preferences.get("profil", {}),
        "category": preferences.get("categories", {}).get(category, {}),
        "general_rules": preferences.get("regles_generales", {}),
    }


def article_ai_context(article, preferences, max_content_chars=12000):
    content = article.get("content", "")
    return {
        "article_id": article.get("article_id") or article_id(article["url"]),
        "title": article["title"],
        "description": article["description"],
        "content": content[:max_content_chars],
        "published": article["published"],
        "source": article["source"],
        "category": article["category"],
        "interest_score": article.get("interest_score"),
        "preference_context": preference_context(preferences, article["category"]),
    }


def article_age_days(article, now=None):
    if not article["published"]:
        return None
    try:
        published = datetime.fromisoformat(article["published"].replace("Z", "+00:00"))
    except ValueError:
        return None
    now = now or datetime.now(timezone.utc)
    return max(0, (now - published).total_seconds() / 86400)


def score_article(article, now=None):
    keywords = article.get("keywords", [])
    excluded_keywords = article.get("excluded_keywords", [])
    searchable_text = clean_text(
        f'{article["title"]} {article["description"]} {article["content"]}'
    ).lower()
    matched_keywords = [keyword for keyword in keywords if clean_text(keyword).lower() in searchable_text]
    matched_excluded = [
        keyword for keyword in excluded_keywords if clean_text(keyword).lower() in searchable_text
    ]
    age = article_age_days(article, now=now)
    freshness_score = 30 if age is None else max(0, 30 - min(age, 30))
    keyword_score = min(30, len(matched_keywords) * 10)
    completeness_score = 10 if article["content"] else (5 if article["description"] else 0)
    score = max(0, min(100, freshness_score + keyword_score + completeness_score))
    return score, {
        "freshness": round(freshness_score, 1),
        "matched_keywords": matched_keywords,
        "excluded_keywords": matched_excluded,
        "completeness": completeness_score,
    }


def deduplicate_articles(articles):
    unique_articles = []
    by_url = {}
    for article in articles:
        article["canonical_url"] = canonical_url(article["url"])
        duplicate = by_url.get(article["canonical_url"])
        if duplicate is None:
            for candidate in unique_articles:
                if candidate["category"] == article["category"] and article_similarity(candidate, article) >= 0.92:
                    duplicate = candidate
                    break
        if duplicate is None:
            article["related_sources"] = [article["source"]]
            article["duplicate_count"] = 1
            by_url[article["canonical_url"]] = article
            unique_articles.append(article)
            continue
        duplicate["duplicate_count"] += 1
        if article["source"] not in duplicate["related_sources"]:
            duplicate["related_sources"].append(article["source"])
        if article["interest_score"] > duplicate["interest_score"]:
            article["related_sources"] = duplicate["related_sources"]
            article["duplicate_count"] = duplicate["duplicate_count"]
            unique_articles[unique_articles.index(duplicate)] = article
            by_url[article["canonical_url"]] = article
    return unique_articles


def filter_and_rank_articles(articles, category=None, max_age_days=DEFAULT_MAX_AGE_DAYS,
                             max_per_category=DEFAULT_MAX_PER_CATEGORY):
    now = datetime.now(timezone.utc)
    prepared = []
    for article in articles:
        if category and article["category"].lower() != category.lower():
            continue
        age = article_age_days(article, now=now)
        if max_age_days is not None and age is not None and age > max_age_days:
            continue
        score, reasons = score_article(article, now=now)
        if reasons["excluded_keywords"]:
            continue
        article["interest_score"] = score
        article["score_details"] = reasons
        prepared.append(article)

    prepared = deduplicate_articles(prepared)
    prepared.sort(key=lambda article: (article["interest_score"], article["published"]), reverse=True)
    category_counts = {}
    ranked = []
    for article in prepared:
        current_count = category_counts.get(article["category"], 0)
        if max_per_category is not None and current_count >= max_per_category:
            continue
        category_counts[article["category"]] = current_count + 1
        ranked.append(article)
    return ranked


def main():
    parser = argparse.ArgumentParser(description="Collecte RSS/Atom et extraction d'articles")
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES_FILE)
    parser.add_argument("--preferences", type=Path, default=DEFAULT_PREFERENCES_FILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_FILE)
    parser.add_argument("--without-content", action="store_true")
    parser.add_argument("--category", help="Ne conserver qu'une categorie")
    parser.add_argument("--max-age-days", type=float, default=DEFAULT_MAX_AGE_DAYS)
    parser.add_argument("--max-per-category", type=int, default=DEFAULT_MAX_PER_CATEGORY)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    with args.sources.open(encoding="utf-8") as sources_file:
        sources = json.load(sources_file)
    preferences = load_preferences(args.preferences)
    articles = collect_sources(sources, extract_content=not args.without_content)
    articles = filter_and_rank_articles(
        articles,
        category=args.category,
        max_age_days=args.max_age_days,
        max_per_category=args.max_per_category,
    )
    with args.output.open("w", encoding="utf-8") as output_file:
        json.dump(articles, output_file, ensure_ascii=False, indent=2)
    logging.info("%d article(s) ecrit(s) dans %s", len(articles), args.output)
    end = time.time()
    logging.info("Temps d'execution: %.2f secondes", end - start)


if __name__ == "__main__":
    main()
