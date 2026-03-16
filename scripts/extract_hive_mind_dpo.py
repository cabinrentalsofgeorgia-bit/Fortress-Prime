import os
import json
import logging
from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [HIVE MIND EXTRACT] - %(message)s')

# Default aligns with active Fortress backend config when env is absent.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://fgp_app:fortress2024@localhost:5432/fortress_guest",
)


def _fetch_rows(conn):
    """Fetch accepted telemetry from either legacy or live schema."""
    # Legacy schema (requested format)
    try:
        result = conn.execute(
            text(
                """
                SELECT module_type, original_swarm_text, human_edited_text
                FROM public.legal_hive_mind_feedback_events
                WHERE accepted = true
                ORDER BY created_at ASC
                """
            )
        )
        return [
            {
                "module_type": row.module_type,
                "original_swarm_text": row.original_swarm_text,
                "human_edited_text": row.human_edited_text,
            }
            for row in result
        ]
    except Exception:
        # Clear failed transaction before fallback query on same connection.
        conn.rollback()
        # Live schema currently used by Fortress telemetry route
        result = conn.execute(
            text(
                """
                SELECT source_route, draft_text, final_text
                FROM public.legal_hive_mind_feedback_events
                WHERE outcome_label = 'accepted'
                ORDER BY created_at ASC
                """
            )
        )
        return [
            {
                "module_type": row.source_route,
                "original_swarm_text": row.draft_text,
                "human_edited_text": row.final_text,
            }
            for row in result
        ]


def extract_dpo_dataset(nas_output_path: str):
    """
    Pull accepted telemetry edits and format as JSONL for Unsloth DPO.
    """
    logging.info("Connecting to Postgres to extract Hive Mind telemetry...")
    engine = create_engine(DATABASE_URL)

    dataset_records = []

    try:
        with engine.connect() as conn:
            rows = _fetch_rows(conn)
            for row in rows:
                module_type = (row.get("module_type") or "discovery_interrogatory").replace("_", " ")
                # Constructing the DPO triplet
                record = {
                    "prompt": (
                        "System: You are an elite litigation strategist. Task: "
                        f"Generate a {module_type} based on the provided case facts.\n\n"
                        "Output the drafted legal text."
                    ),
                    "chosen": row.get("human_edited_text") or "",
                    "rejected": row.get("original_swarm_text") or "",
                }
                if record["chosen"] and record["rejected"]:
                    dataset_records.append(record)

        if not dataset_records:
            logging.warning("No accepted telemetry found. Skipping dataset generation.")
            return

        # Write to NAS (or local staging directory)
        os.makedirs(os.path.dirname(nas_output_path), exist_ok=True)
        with open(nas_output_path, "w", encoding="utf-8") as f:
            for record in dataset_records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        logging.info("Successfully extracted %s DPO records to %s", len(dataset_records), nas_output_path)

    except Exception as e:
        logging.error("Failed to extract DPO dataset: %s", e)
        raise


if __name__ == "__main__":
    target_path = os.getenv("DPO_DATASET_PATH", "/home/admin/Fortress-Prime/data/training/hive_mind_dpo.jsonl")
    extract_dpo_dataset(target_path)
