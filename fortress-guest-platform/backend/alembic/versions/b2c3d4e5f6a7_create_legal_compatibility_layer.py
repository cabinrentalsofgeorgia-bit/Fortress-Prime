"""create legal compatibility layer

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f7
Create Date: 2026-03-30 22:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Writable compatibility views for legacy graph services.
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE VIEW legal.legal_cases AS
            SELECT
                c.id,
                c.case_slug AS slug,
                c.case_slug,
                c.court,
                c.case_type AS jurisdiction,
                c.status,
                c.created_at
            FROM legal.cases c
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE OR REPLACE VIEW legal.case_graph_nodes AS
            SELECT
                n.id,
                c.id AS case_id,
                n.entity_type,
                n.label,
                n.properties_json AS metadata,
                NULL::timestamptz AS created_at
            FROM legal.case_graph_nodes_v2 n
            JOIN legal.cases c ON c.case_slug = n.case_slug
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION legal.case_graph_nodes_view_write()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
                resolved_case_slug text;
            BEGIN
                IF TG_OP = 'INSERT' THEN
                    SELECT case_slug INTO resolved_case_slug
                    FROM legal.cases
                    WHERE id = NEW.case_id;

                    IF resolved_case_slug IS NULL THEN
                        RAISE EXCEPTION 'No legal.cases row for case_id %', NEW.case_id;
                    END IF;

                    INSERT INTO legal.case_graph_nodes_v2 (
                        id, case_slug, entity_type, entity_reference_id, label, properties_json
                    ) VALUES (
                        COALESCE(NEW.id, gen_random_uuid()),
                        resolved_case_slug,
                        NEW.entity_type,
                        NULL,
                        NEW.label,
                        COALESCE(NEW.metadata, '{}'::jsonb)
                    );
                    RETURN NEW;
                ELSIF TG_OP = 'DELETE' THEN
                    DELETE FROM legal.case_graph_nodes_v2 WHERE id = OLD.id;
                    RETURN OLD;
                END IF;
                RETURN NULL;
            END;
            $$;
            """
        )
    )
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_case_graph_nodes_view_write ON legal.case_graph_nodes"))
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_case_graph_nodes_view_write
            INSTEAD OF INSERT OR DELETE ON legal.case_graph_nodes
            FOR EACH ROW EXECUTE FUNCTION legal.case_graph_nodes_view_write()
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE OR REPLACE VIEW legal.case_graph_edges AS
            SELECT
                e.id,
                c.id AS case_id,
                e.source_node_id,
                e.target_node_id,
                e.relationship_type,
                e.weight,
                NULL::text AS source_ref,
                NULL::timestamptz AS created_at
            FROM legal.case_graph_edges_v2 e
            JOIN legal.cases c ON c.case_slug = e.case_slug
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION legal.case_graph_edges_view_write()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
                resolved_case_slug text;
            BEGIN
                IF TG_OP = 'INSERT' THEN
                    SELECT case_slug INTO resolved_case_slug
                    FROM legal.cases
                    WHERE id = NEW.case_id;

                    IF resolved_case_slug IS NULL THEN
                        RAISE EXCEPTION 'No legal.cases row for case_id %', NEW.case_id;
                    END IF;

                    INSERT INTO legal.case_graph_edges_v2 (
                        id, case_slug, source_node_id, target_node_id, relationship_type, weight, source_evidence_id
                    ) VALUES (
                        COALESCE(NEW.id, gen_random_uuid()),
                        resolved_case_slug,
                        NEW.source_node_id,
                        NEW.target_node_id,
                        NEW.relationship_type,
                        COALESCE(NEW.weight, 1.0),
                        NULL
                    );
                    RETURN NEW;
                ELSIF TG_OP = 'DELETE' THEN
                    DELETE FROM legal.case_graph_edges_v2 WHERE id = OLD.id;
                    RETURN OLD;
                END IF;
                RETURN NULL;
            END;
            $$;
            """
        )
    )
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_case_graph_edges_view_write ON legal.case_graph_edges"))
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_case_graph_edges_view_write
            INSTEAD OF INSERT OR DELETE ON legal.case_graph_edges
            FOR EACH ROW EXECUTE FUNCTION legal.case_graph_edges_view_write()
            """
        )
    )

    # Read-only compatibility views for legacy names that now live in v2 tables.
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE VIEW legal.discovery_draft_packs AS
            SELECT
                p.id,
                c.id AS case_id,
                p.case_slug,
                p.target_entity AS pack_type,
                p.status,
                p.created_at
            FROM legal.discovery_draft_packs_v2 p
            JOIN legal.cases c ON c.case_slug = p.case_slug
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE VIEW legal.discovery_draft_items AS
            SELECT
                i.id,
                i.pack_id,
                i.sequence_number AS item_number,
                i.category,
                i.content,
                i.rationale_from_graph,
                i.lethality_score,
                i.proportionality_score,
                i.correction_notes
            FROM legal.discovery_draft_items_v2 i
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE VIEW legal.sanctions_alerts AS
            SELECT
                id,
                case_slug,
                alert_type,
                NULL::text AS filing_ref,
                contradiction_summary,
                NULL::text AS draft_content_ref,
                status,
                created_at
            FROM legal.sanctions_alerts_v2
            """
        )
    )

    # Missing legal tables used directly by chronology and graph services.
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS legal.case_statements (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                case_slug TEXT NOT NULL,
                entity_name TEXT NOT NULL,
                quote_text TEXT NOT NULL,
                source_ref TEXT NOT NULL,
                doc_id TEXT,
                stated_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_legal_case_statements_case_slug ON legal.case_statements (case_slug)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_legal_case_statements_doc_id ON legal.case_statements (doc_id)"))

    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS legal.chronology_events (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                case_slug TEXT NOT NULL,
                event_date DATE NOT NULL,
                event_description TEXT NOT NULL,
                entities_involved JSONB NOT NULL DEFAULT '[]'::jsonb,
                source_ref TEXT,
                event_type TEXT,
                significance TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_legal_chronology_events_case_slug ON legal.chronology_events (case_slug)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_legal_chronology_events_event_date ON legal.chronology_events (event_date)"))

    op.execute(sa.text("GRANT SELECT ON legal.legal_cases TO fortress_api"))
    op.execute(sa.text("GRANT SELECT, INSERT, DELETE ON legal.case_graph_nodes TO fortress_api"))
    op.execute(sa.text("GRANT SELECT, INSERT, DELETE ON legal.case_graph_edges TO fortress_api"))
    op.execute(sa.text("GRANT SELECT ON legal.discovery_draft_packs TO fortress_api"))
    op.execute(sa.text("GRANT SELECT ON legal.discovery_draft_items TO fortress_api"))
    op.execute(sa.text("GRANT SELECT ON legal.sanctions_alerts TO fortress_api"))
    op.execute(sa.text("GRANT SELECT, INSERT, UPDATE, DELETE ON legal.case_statements TO fortress_api"))
    op.execute(sa.text("GRANT SELECT, INSERT, UPDATE, DELETE ON legal.chronology_events TO fortress_api"))


def downgrade() -> None:
    op.execute(sa.text("REVOKE ALL ON legal.chronology_events FROM fortress_api"))
    op.execute(sa.text("REVOKE ALL ON legal.case_statements FROM fortress_api"))
    op.execute(sa.text("REVOKE ALL ON legal.sanctions_alerts FROM fortress_api"))
    op.execute(sa.text("REVOKE ALL ON legal.discovery_draft_items FROM fortress_api"))
    op.execute(sa.text("REVOKE ALL ON legal.discovery_draft_packs FROM fortress_api"))
    op.execute(sa.text("REVOKE ALL ON legal.case_graph_edges FROM fortress_api"))
    op.execute(sa.text("REVOKE ALL ON legal.case_graph_nodes FROM fortress_api"))
    op.execute(sa.text("REVOKE ALL ON legal.legal_cases FROM fortress_api"))

    op.execute(sa.text("DROP INDEX IF EXISTS legal.ix_legal_chronology_events_event_date"))
    op.execute(sa.text("DROP INDEX IF EXISTS legal.ix_legal_chronology_events_case_slug"))
    op.execute(sa.text("DROP TABLE IF EXISTS legal.chronology_events"))

    op.execute(sa.text("DROP INDEX IF EXISTS legal.ix_legal_case_statements_doc_id"))
    op.execute(sa.text("DROP INDEX IF EXISTS legal.ix_legal_case_statements_case_slug"))
    op.execute(sa.text("DROP TABLE IF EXISTS legal.case_statements"))

    op.execute(sa.text("DROP VIEW IF EXISTS legal.sanctions_alerts"))
    op.execute(sa.text("DROP VIEW IF EXISTS legal.discovery_draft_items"))
    op.execute(sa.text("DROP VIEW IF EXISTS legal.discovery_draft_packs"))

    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_case_graph_edges_view_write ON legal.case_graph_edges"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS legal.case_graph_edges_view_write()"))
    op.execute(sa.text("DROP VIEW IF EXISTS legal.case_graph_edges"))

    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_case_graph_nodes_view_write ON legal.case_graph_nodes"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS legal.case_graph_nodes_view_write()"))
    op.execute(sa.text("DROP VIEW IF EXISTS legal.case_graph_nodes"))

    op.execute(sa.text("DROP VIEW IF EXISTS legal.legal_cases"))
