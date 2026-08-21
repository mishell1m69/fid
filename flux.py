import time
import argparse
import html
import json
import logging
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import feedparser
import trafilatura

start = time.time()

DEFAULT_SOURCES_FILE = Path(__file__).with_name("sources.json")
DEFAULT_OUTPUT_FILE = Path(__file__).with_name("articles.json")
USER_AGENT = "veille-personnalisee/1.0"


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
        "title": clean_text(entry.get("title")),
        "url": entry.get("link", ""),
        "published": entry_date(entry),
        "description": clean_text(description),
        "content": extract_article(entry) if extract_content else "",
        "source": source["nom"],
        "category": source["categorie"],
        "feed_url": feed_url,
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


def main():
    parser = argparse.ArgumentParser(description="Collecte RSS/Atom et extraction d'articles")
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES_FILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_FILE)
    parser.add_argument("--without-content", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    with args.sources.open(encoding="utf-8") as sources_file:
        sources = json.load(sources_file)
    articles = collect_sources(sources, extract_content=not args.without_content)
    with args.output.open("w", encoding="utf-8") as output_file:
        json.dump(articles, output_file, ensure_ascii=False, indent=2)
    logging.info("%d article(s) ecrit(s) dans %s", len(articles), args.output)
    end = time.time()
    logging.info("Temps d'execution: %.2f secondes", end - start)


if __name__ == "__main__":
    main()
