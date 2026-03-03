"""
Fortress Prime — Legal Clerk: O.C.G.A. Statute Scraper
Crawls law.onecle.com for Georgia Code titles and saves
clean statute text for vectorization into ChromaDB.

Usage:
    python division_legal/ingest_law.py
    python division_legal/ingest_law.py --titles 16 44 51 9
"""
import os
import re
import sys
import time
import requests
from bs4 import BeautifulSoup

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)

# --- CONFIG ---
BASE_URL = "https://law.onecle.com/georgia"
KNOWLEDGE_BASE = os.path.join(os.path.dirname(__file__), "knowledge_base")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}
DELAY = 0.5  # Be respectful — half-second between requests

# Target titles for a Sovereign Real Estate & Legal AI
DEFAULT_TITLES = [
    44,  # Property (Landlord/Tenant, Deeds, Easements, Mortgages)
    16,  # Crimes and Offenses (Theft, Fraud, Trespass)
    51,  # Torts (Liability, Negligence, Damages)
    9,   # Civil Practice (How to file lawsuits)
    13,  # Contracts
    48,  # Revenue and Taxation
]


def fetch(url):
    """Fetch a page with retry logic."""
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                return BeautifulSoup(r.text, "lxml")
            elif r.status_code == 429:
                print(f"      Rate limited. Waiting 10s...")
                time.sleep(10)
            else:
                print(f"      HTTP {r.status_code} for {url}")
                return None
        except Exception as e:
            print(f"      Error: {e}. Retry {attempt+1}/3...")
            time.sleep(2)
    return None


def extract_statute_text(soup):
    """Extract clean statute text from a section page."""
    # The statute text is typically in the page body after the title
    # Remove navigation, ads, headers
    for tag in soup.find_all(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    # Try to find the main content
    text = soup.get_text(separator="\n", strip=True)

    # Clean: find the statute content between known markers
    lines = text.split("\n")
    content_lines = []
    capture = False
    for line in lines:
        line = line.strip()
        # Start capturing at the section number pattern
        if re.match(r"^\(a\)", line) or re.match(r"^The\s", line) or re.match(r"^A\s", line) or re.match(r"^Each\s", line) or re.match(r"^No\s", line) or re.match(r"^Any\s", line) or re.match(r"^When\s", line) or re.match(r"^In\s", line) or re.match(r"^Unless\s", line) or re.match(r"^It\s", line) or re.match(r"^Except\s", line):
            capture = True
        if capture:
            # Stop at navigation/footer markers
            if any(x in line.lower() for x in ["disclaimer", "onecle", "attorney", "lawyer directory", "home", "incorporation"]):
                break
            if line.startswith("§") and content_lines:
                break  # Next section started
            if line:
                content_lines.append(line)

    return "\n".join(content_lines)


def scrape_section(url, section_id):
    """Scrape a single statute section."""
    soup = fetch(url)
    if not soup:
        return None

    # Get the title from the page
    title_tag = soup.find("h1") or soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else section_id

    # Clean the title
    title = re.sub(r"\s*-\s*Georgia Attorney.*$", "", title)
    title = re.sub(r"^Georgia Code\s*", "", title)

    # Extract body text
    body = extract_statute_text(soup)

    if body and len(body) > 20:
        return f"§ {section_id}\n{title}\n\n{body}"
    return None


def scrape_article(title_num, chapter_slug, article_slug, article_name):
    """Scrape all sections in an article."""
    url = f"{BASE_URL}/title-{title_num}/{chapter_slug}/{article_slug}/index.html"
    soup = fetch(url)
    if not soup:
        return []

    sections = []
    for a in soup.find_all("a"):
        href = a.get("href", "")
        text = a.get_text(strip=True)
        # Match section links like /georgia/title-44/44-7-1.html
        if f"{title_num}-" in href and href.endswith(".html") and "§" in text:
            section_id = re.search(r"(\d+-\d+-[\d\.]+)", href)
            if section_id:
                sid = section_id.group(1)
                full_url = f"https://law.onecle.com{href}" if href.startswith("/") else href
                time.sleep(DELAY)
                statute = scrape_section(full_url, sid)
                if statute:
                    sections.append(statute)
                    print(f"         ✓ § {sid}")

    return sections


def scrape_chapter(title_num, chapter_slug, chapter_name):
    """Scrape all articles/sections in a chapter."""
    url = f"{BASE_URL}/title-{title_num}/{chapter_slug}/index.html"
    soup = fetch(url)
    if not soup:
        return []

    all_sections = []

    # Check if chapter has articles or direct sections
    articles = []
    direct_sections = []

    for a in soup.find_all("a"):
        href = a.get("href", "")
        text = a.get_text(strip=True)

        if "article-" in href.lower() and text and "Art." not in text[:5]:
            articles.append((href.split("/")[-2], text))
        elif f"{title_num}-" in href and href.endswith(".html") and "§" in text:
            section_id = re.search(r"(\d+-\d+-[\d\.]+)", href)
            if section_id:
                direct_sections.append((href, section_id.group(1)))

    if articles:
        for art_slug, art_name in articles:
            # Filter out constitution articles that leak in
            if "constitution" in art_slug:
                continue
            print(f"      📖 {art_name}")
            secs = scrape_article(title_num, chapter_slug, art_slug, art_name)
            all_sections.extend(secs)
    elif direct_sections:
        # Sections directly under chapter (no articles)
        for href, sid in direct_sections:
            full_url = f"https://law.onecle.com{href}" if href.startswith("/") else href
            time.sleep(DELAY)
            statute = scrape_section(full_url, sid)
            if statute:
                all_sections.append(statute)
                print(f"         ✓ § {sid}")

    return all_sections


def scrape_title(title_num):
    """Scrape an entire Title of the Georgia Code."""
    print(f"\n📜 SCRAPING TITLE {title_num}...")
    url = f"{BASE_URL}/title-{title_num}/index.html"
    soup = fetch(url)
    if not soup:
        print(f"   ❌ Failed to load Title {title_num}")
        return

    # Get title name
    h1 = soup.find("h1")
    title_name = h1.get_text(strip=True) if h1 else f"Title {title_num}"
    print(f"   {title_name}")

    # Find chapters
    chapters = []
    for a in soup.find_all("a"):
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if "chapter-" in href.lower() and text and "Chapter" in text:
            chapter_slug = href.replace("/index.html", "").split("/")[-1]
            if chapter_slug.startswith("chapter-"):
                chapters.append((chapter_slug, text))

    print(f"   Found {len(chapters)} chapters.\n")

    all_statutes = [f"OFFICIAL CODE OF GEORGIA ANNOTATED\n{title_name}\n{'='*60}\n"]
    total_sections = 0

    for ch_slug, ch_name in chapters:
        print(f"   📂 {ch_name}")
        sections = scrape_chapter(title_num, ch_slug, ch_name)
        if sections:
            all_statutes.append(f"\n{'='*60}")
            all_statutes.append(f"{ch_name}")
            all_statutes.append(f"{'='*60}\n")
            all_statutes.extend(sections)
            total_sections += len(sections)

    # Save to file
    os.makedirs(KNOWLEDGE_BASE, exist_ok=True)
    output_file = os.path.join(KNOWLEDGE_BASE, f"Title_{title_num}.txt")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n\n".join(all_statutes))

    file_size = os.path.getsize(output_file) / 1024
    print(f"\n   ✅ TITLE {title_num} COMPLETE: {total_sections} sections, {file_size:.0f} KB")
    print(f"   📄 Saved to: {output_file}")


def main():
    titles = DEFAULT_TITLES

    # Allow custom titles via command line
    if "--titles" in sys.argv:
        idx = sys.argv.index("--titles")
        titles = [int(t) for t in sys.argv[idx + 1:]]

    print("⚖️  FORTRESS PRIME: LEGAL CLERK — O.C.G.A. INGESTION")
    print(f"   Targets: Titles {titles}")
    print(f"   Source: {BASE_URL}")
    print(f"   Output: {KNOWLEDGE_BASE}\n")

    for title_num in titles:
        scrape_title(title_num)
        print()

    # Summary
    print("\n" + "=" * 60)
    print("📚 LAW SCHOOL ENROLLMENT COMPLETE")
    print("=" * 60)
    for title_num in titles:
        f = os.path.join(KNOWLEDGE_BASE, f"Title_{title_num}.txt")
        if os.path.exists(f):
            size = os.path.getsize(f) / 1024
            print(f"   Title {title_num}: {size:.0f} KB")
    print(f"\nNext step: Run chroma_loader.py to vectorize into law_library.")


if __name__ == "__main__":
    main()
