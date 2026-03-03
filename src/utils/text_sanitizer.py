"""
FORTRESS PRIME — Email Text Sanitizer
======================================
Strips HTML tags, CSS, JS, invisible characters, and normalizes whitespace
from raw email bodies before feeding them to the LLM classifier.

AI models hallucinate on raw HTML. All emails must pass through this first.
"""

import re
from html import unescape
import unicodedata
from bs4 import BeautifulSoup

_INVISIBLE_RE = re.compile(r'[\u200b\u200c\u200d\u200e\u200f\ufeff\u00ad\u2060\u2061\u2062\u2063\u2064]')
_WHITESPACE_RE = re.compile(r'[ \t]+')
_BLANK_LINES_RE = re.compile(r'\n{3,}')


def sanitize_email_text(raw: str, max_length: int = 5000) -> str:
    """Strip HTML and normalize whitespace from an email body.

    Args:
        raw: Raw email body (may be HTML or plain text).
        max_length: Truncate output to this many characters.

    Returns:
        Clean, readable plain text suitable for LLM classification.
    """
    if not raw or not isinstance(raw, str):
        return ""

    text = raw

    if _looks_like_html(text):
        try:
            soup = BeautifulSoup(text, "html.parser")
            for tag in soup.find_all(["style", "script", "head", "meta", "link", "noscript"]):
                tag.decompose()
            text = soup.get_text(separator=" ")
        except Exception:
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<[^>]+>', ' ', text)

    text = unescape(text)
    text = text.replace("&nbsp;", " ")
    text = re.sub(r'&[a-zA-Z]+;', ' ', text)
    text = re.sub(r'&#\d+;', ' ', text)
    text = _INVISIBLE_RE.sub('', text)
    text = unicodedata.normalize('NFKC', text)
    text = _WHITESPACE_RE.sub(' ', text)
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = _BLANK_LINES_RE.sub('\n\n', text)
    text = text.strip()

    if len(text) > max_length:
        text = text[:max_length] + "..."

    return text


def _looks_like_html(text: str) -> bool:
    """Heuristic check for HTML content."""
    if not text:
        return False
    sample = text[:2000].lower()
    indicators = ['<html', '<body', '<div', '<table', '<p ', '<br', '<span', '<a href', '<!doctype']
    return any(tag in sample for tag in indicators)
