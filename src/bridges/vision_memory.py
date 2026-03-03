"""
FORTRESS PRIME — The Retina (Visual Cortex Schema)
====================================================
Creates the ops_visuals table: the structured memory for everything
the AI "sees" when processing images across the NAS.

Links physical file paths → AI descriptions → ChromaDB vectors → properties.

Usage:
    python3 src/bridges/vision_memory.py
"""

import os
import sys
import psycopg2

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
except ImportError:
    pass


def build_retina():
    """Construct the Visual Cortex tables in PostgreSQL."""
    print("  CONSTRUCTING VISUAL CORTEX...")

    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "fortress_db"),
        user=os.getenv("DB_USER", "miner_bot"),
        password=os.getenv("DB_PASSWORD", os.getenv("DB_PASS", "")),
    )
    cur = conn.cursor()

    # ─── THE VISUAL INDEX ────────────────────────────────────────────────
    # Every image the system has ever "seen" gets a row here.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ops_visuals (
            image_id        SERIAL PRIMARY KEY,
            file_path       TEXT UNIQUE NOT NULL,
            file_name       VARCHAR(255),
            file_size_bytes BIGINT,
            file_ext        VARCHAR(10),

            -- Property linkage (matched from folder name → ops_properties)
            property_id     VARCHAR(50) REFERENCES ops_properties(property_id)
                            ON DELETE SET NULL,
            property_name   VARCHAR(200),

            -- What the AI sees
            description     TEXT,
            features        JSONB DEFAULT '{}',
            room_type       VARCHAR(50),
            quality_score   NUMERIC(5, 2),

            -- Vector linkage
            embedding_id    VARCHAR(100),
            collection_name VARCHAR(100) DEFAULT 'fortress_docs',

            -- Processing metadata
            model_used      VARCHAR(100),
            inference_time_s REAL,
            status          VARCHAR(20) DEFAULT 'PENDING',
            error_message   TEXT,
            scanned_at      TIMESTAMP,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # ─── INDEXES ─────────────────────────────────────────────────────────
    cur.execute("CREATE INDEX IF NOT EXISTS idx_vis_path     ON ops_visuals(file_path);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_vis_prop     ON ops_visuals(property_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_vis_propname ON ops_visuals(property_name);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_vis_status   ON ops_visuals(status);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_vis_ext      ON ops_visuals(file_ext);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_vis_room     ON ops_visuals(room_type);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_vis_scanned  ON ops_visuals(scanned_at);")

    # ─── VISION RUN LOG ──────────────────────────────────────────────────
    # Track each batch run for auditing and resumability
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vision_runs (
            run_id          SERIAL PRIMARY KEY,
            scan_path       TEXT NOT NULL,
            model_used      VARCHAR(100),
            images_found    INTEGER DEFAULT 0,
            images_processed INTEGER DEFAULT 0,
            images_failed   INTEGER DEFAULT 0,
            images_skipped  INTEGER DEFAULT 0,
            started_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at    TIMESTAMP,
            status          VARCHAR(20) DEFAULT 'RUNNING'
        );
    """)

    conn.commit()
    conn.close()

    print("  Retina Ready: ops_visuals + vision_runs created.")
    print("  The Eye can now store what it sees.")


if __name__ == "__main__":
    build_retina()
