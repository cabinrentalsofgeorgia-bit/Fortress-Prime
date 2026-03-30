"""fix legal compatibility uuid ids

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-30 22:40:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID_NAMESPACE = "6ba7b811-9dad-11d1-80b4-00c04fd430c8"


def upgrade() -> None:
    op.execute(sa.text("DROP VIEW IF EXISTS legal.discovery_draft_packs"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_case_graph_edges_view_write ON legal.case_graph_edges"))
    op.execute(sa.text("DROP VIEW IF EXISTS legal.case_graph_edges"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_case_graph_nodes_view_write ON legal.case_graph_nodes"))
    op.execute(sa.text("DROP VIEW IF EXISTS legal.case_graph_nodes"))
    op.execute(sa.text("DROP VIEW IF EXISTS legal.legal_cases"))

    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE VIEW legal.legal_cases AS
            SELECT
                uuid_generate_v5('{UUID_NAMESPACE}'::uuid, c.case_slug) AS id,
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
            f"""
            CREATE OR REPLACE VIEW legal.case_graph_nodes AS
            SELECT
                n.id,
                uuid_generate_v5('{UUID_NAMESPACE}'::uuid, c.case_slug) AS case_id,
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
            f"""
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
                    WHERE uuid_generate_v5('{UUID_NAMESPACE}'::uuid, case_slug) = NEW.case_id;

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
                        COALESCE(NEW.metadata, '{{}}'::jsonb)
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

    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE VIEW legal.case_graph_edges AS
            SELECT
                e.id,
                uuid_generate_v5('{UUID_NAMESPACE}'::uuid, c.case_slug) AS case_id,
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
            f"""
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
                    WHERE uuid_generate_v5('{UUID_NAMESPACE}'::uuid, case_slug) = NEW.case_id;

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

    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE VIEW legal.discovery_draft_packs AS
            SELECT
                p.id,
                uuid_generate_v5('{UUID_NAMESPACE}'::uuid, c.case_slug) AS case_id,
                p.case_slug,
                p.target_entity AS pack_type,
                p.status,
                p.created_at
            FROM legal.discovery_draft_packs_v2 p
            JOIN legal.cases c ON c.case_slug = p.case_slug
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP VIEW IF EXISTS legal.discovery_draft_packs"))
    op.execute(sa.text("DROP VIEW IF EXISTS legal.case_graph_edges"))
    op.execute(sa.text("DROP VIEW IF EXISTS legal.case_graph_nodes"))
    op.execute(sa.text("DROP VIEW IF EXISTS legal.legal_cases"))

    # Restore integer-backed compatibility ids.
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
