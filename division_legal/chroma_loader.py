"""
Fortress Prime — Legal Vectorizer: ChromaDB Loader
Reads scraped Title_XX.txt files, splits them by section (§),
embeds each statute using Ollama nomic-embed-text, and loads
them into the 'law_library' ChromaDB collection.

Usage:
    python division_legal/chroma_loader.py
"""
import os
import re
import chromadb
import requests

# --- CONFIG ---
KNOWLEDGE_BASE = os.path.join(os.path.dirname(__file__), "knowledge_base")
CHROMA_PATH = os.path.join(os.path.dirname(__file__), "chroma_db")
OLLAMA_EMBED_URL = "http://localhost:11434/api/embeddings"
EMBED_MODEL = "nomic-embed-text:latest"
COLLECTION_NAME = "law_library"


def get_embedding(text):
    """Get embedding vector from Ollama nomic-embed-text."""
    try:
        r = requests.post(OLLAMA_EMBED_URL, json={
            "model": EMBED_MODEL,
            "prompt": text
        }, timeout=30)
        if r.status_code == 200:
            return r.json().get("embedding")
    except Exception as e:
        print(f"      Embedding error: {e}")
    return None


def split_into_sections(text, title_num):
    """Split a Title text file into individual statute sections."""
    # Split on the section symbol pattern: § XX-YY-ZZ
    sections = re.split(r'\n(?=§\s*\d)', text)

    statutes = []
    for section in sections:
        section = section.strip()
        if not section or len(section) < 30:
            continue

        # Extract section number
        match = re.match(r'§\s*([\d\-\.]+)', section)
        if match:
            section_id = match.group(1)
            statutes.append({
                "id": f"ocga_{section_id}",
                "section": section_id,
                "title": title_num,
                "text": section[:2000],  # Cap at 2000 chars for embedding
                "full_text": section
            })

    return statutes


def load_title(title_num, collection):
    """Load a single Title into ChromaDB."""
    filepath = os.path.join(KNOWLEDGE_BASE, f"Title_{title_num}.txt")
    if not os.path.exists(filepath):
        print(f"   ❌ Title_{title_num}.txt not found in knowledge_base/")
        return 0

    print(f"\n📜 VECTORIZING TITLE {title_num}...")
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()

    statutes = split_into_sections(text, title_num)
    print(f"   Found {len(statutes)} sections to embed.")

    indexed = 0
    for i, statute in enumerate(statutes):
        # Check if already indexed
        existing = collection.get(ids=[statute["id"]])
        if existing and existing["ids"]:
            continue

        # Get embedding
        embedding = get_embedding(statute["text"])
        if not embedding:
            continue

        # Store in ChromaDB
        collection.add(
            ids=[statute["id"]],
            embeddings=[embedding],
            documents=[statute["full_text"]],
            metadatas=[{
                "section": statute["section"],
                "title": str(title_num),
                "source": f"O.C.G.A. Title {title_num}",
                "source_file": filepath
            }]
        )
        indexed += 1

        if (i + 1) % 25 == 0:
            print(f"      Embedded {i+1}/{len(statutes)}...")

    print(f"   ✅ Indexed {indexed} NEW statutes for Title {title_num}")
    return indexed


def main():
    print("⚖️  FORTRESS PRIME: BAR EXAM — VECTORIZING THE LAW")
    print(f"   ChromaDB: {CHROMA_PATH}")
    print(f"   Embed Model: {EMBED_MODEL}")
    print(f"   Collection: {COLLECTION_NAME}\n")

    # Initialize ChromaDB
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"description": "Official Code of Georgia Annotated"}
    )

    # Check existing count
    existing = collection.count()
    print(f"   Existing embeddings: {existing}")

    # Find all Title files
    title_files = sorted([
        f for f in os.listdir(KNOWLEDGE_BASE)
        if f.startswith("Title_") and f.endswith(".txt")
    ])

    if not title_files:
        print("   ❌ No Title files found. Run ingest_law.py first!")
        return

    print(f"   Found {len(title_files)} Title files to process.")

    total_indexed = 0
    for tf in title_files:
        title_num = re.search(r"Title_(\d+)", tf)
        if title_num:
            count = load_title(int(title_num.group(1)), collection)
            total_indexed += count

    # Final report
    final_count = collection.count()
    print(f"\n{'='*60}")
    print(f"📚 BAR EXAM COMPLETE")
    print(f"{'='*60}")
    print(f"   Total statutes in law_library: {final_count}")
    print(f"   New statutes added this run: {total_indexed}")
    print(f"\n   Justicia is ready for consultation.")


if __name__ == "__main__":
    main()
