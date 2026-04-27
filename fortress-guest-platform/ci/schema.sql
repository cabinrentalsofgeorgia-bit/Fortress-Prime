-- CI schema snapshot for fortress-guest-platform
-- Generated: 2026-04-27T19:37:00Z
-- Source:    fortress_snapshot_0a_1
-- Commit:    859e41fc24e5c1f42c6f1f0986dc9a351c205d8c
-- Alembic:   d8e3c1f5b9a6,m8f9a1b2c3d4,q2b3c4d5e6f7
-- NOTE: geometry/vector types replaced with text for CI compatibility.
--       postgis/vector extensions omitted (postgres:16 has pgcrypto/uuid-ossp).

SET statement_timeout = 0;
SET lock_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;

-- Ensure all objects are created as fortress_admin (matches CI role provisioning)
SET ROLE TO fortress_admin;

--
-- PostgreSQL database dump
--

\restrict YJeY4MxXMci8nmcQ37m9ixOtGJPKeF13E2Shgxfwwmv045ww2nmoLEJ8YukyunV

-- Dumped from database version 16.13 (Ubuntu 16.13-0ubuntu0.24.04.1)
-- Dumped by pg_dump version 16.13 (Ubuntu 16.13-0ubuntu0.24.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: core; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA core;


--
-- Name: crog_acquisition; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA crog_acquisition;


--
-- Name: iot_schema; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA iot_schema;


--
-- Name: legal; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA legal;


--
-- Name: verses_schema; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA verses_schema;


--
-- Name: dblink; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS dblink WITH SCHEMA public;


--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: uuid-ossp; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;


--
-- Name: funnel_stage; Type: TYPE; Schema: crog_acquisition; Owner: -
--

CREATE TYPE crog_acquisition.funnel_stage AS ENUM (
    'RADAR',
    'TARGET_LOCKED',
    'DEPLOYED',
    'ENGAGED',
    'ACQUIRED',
    'REJECTED'
);


--
-- Name: market_state; Type: TYPE; Schema: crog_acquisition; Owner: -
--

CREATE TYPE crog_acquisition.market_state AS ENUM (
    'UNMANAGED',
    'CROG_MANAGED',
    'COMPETITOR_MANAGED',
    'FOR_SALE'
);


--
-- Name: signal_source; Type: TYPE; Schema: crog_acquisition; Owner: -
--

CREATE TYPE crog_acquisition.signal_source AS ENUM (
    'FOIA_CSV',
    'OTA_FIRECRAWL_HEURISTIC',
    'AGGREGATOR_API'
);


--
-- Name: guest_quote_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.guest_quote_status AS ENUM (
    'pending',
    'accepted',
    'rejected',
    'expired'
);


--
-- Name: hunter_recovery_op_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.hunter_recovery_op_status AS ENUM (
    'QUEUED',
    'EXECUTING',
    'DRAFT_READY',
    'DISPATCHED',
    'REJECTED'
);


--
-- Name: owner_charge_type_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.owner_charge_type_enum AS ENUM (
    'cleaning_fee',
    'maintenance',
    'management_fee',
    'supplies',
    'landscaping',
    'linen',
    'electric_bill',
    'housekeeper_pay',
    'advertising_fee',
    'third_party_ota_commission',
    'travel_agent_fee',
    'credit_card_dispute',
    'federal_tax_withholding',
    'adjust_owner_revenue',
    'credit_from_management',
    'pay_to_old_owner',
    'misc_guest_charges',
    'statement_marker',
    'room_revenue',
    'hacienda_tax',
    'charge_expired_owner',
    'owner_payment_received'
);


--
-- Name: property_renting_state; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.property_renting_state AS ENUM (
    'active',
    'pre_launch',
    'paused',
    'offboarded'
);


--
-- Name: statement_period_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.statement_period_status AS ENUM (
    'draft',
    'pending_approval',
    'approved',
    'paid',
    'emailed',
    'voided'
);


--
-- Name: prevent_mutation(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.prevent_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    RAISE EXCEPTION 'Immutable table: UPDATE and DELETE are strictly forbidden on %', TG_TABLE_NAME;
    RETURN NULL;
END;
$$;


SET default_table_access_method = heap;

--
-- Name: deliberation_logs; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.deliberation_logs (
    id uuid NOT NULL,
    verdict_type character varying(64) NOT NULL,
    session_id character varying(128) NOT NULL,
    guest_id uuid,
    reservation_id uuid,
    property_id uuid,
    message_id uuid,
    payload_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp without time zone NOT NULL
);


--
-- Name: acquisition_documents; Type: TABLE; Schema: crog_acquisition; Owner: -
--

CREATE TABLE crog_acquisition.acquisition_documents (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    pipeline_id uuid NOT NULL,
    file_name character varying(255) NOT NULL,
    nfs_path text NOT NULL,
    mime_type character varying(100) DEFAULT 'application/octet-stream'::character varying NOT NULL,
    file_hash character varying(64),
    file_size_bytes integer,
    doc_type character varying(50) DEFAULT 'general'::character varying NOT NULL,
    uploaded_by character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: acquisition_pipeline; Type: TABLE; Schema: crog_acquisition; Owner: -
--

CREATE TABLE crog_acquisition.acquisition_pipeline (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    property_id uuid NOT NULL,
    stage crog_acquisition.funnel_stage DEFAULT 'RADAR'::crog_acquisition.funnel_stage NOT NULL,
    llm_viability_score numeric(3,2),
    lob_mail_sent_at timestamp with time zone,
    instantly_campaign_id character varying(255),
    vapi_call_status character varying(100),
    next_action_date date,
    rejection_reason text,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: due_diligence; Type: TABLE; Schema: crog_acquisition; Owner: -
--

CREATE TABLE crog_acquisition.due_diligence (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    pipeline_id uuid NOT NULL,
    item_key character varying(80) NOT NULL,
    label character varying(255) NOT NULL,
    display_order integer DEFAULT 0 NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    notes text,
    completed_at timestamp with time zone,
    completed_by character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT chk_dd_status CHECK (((status)::text = ANY (ARRAY[('pending'::character varying)::text, ('passed'::character varying)::text, ('failed'::character varying)::text, ('waived'::character varying)::text])))
);


--
-- Name: intel_events; Type: TABLE; Schema: crog_acquisition; Owner: -
--

CREATE TABLE crog_acquisition.intel_events (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    property_id uuid NOT NULL,
    event_type character varying(100) NOT NULL,
    event_description text NOT NULL,
    raw_source_data jsonb,
    detected_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: owner_contacts; Type: TABLE; Schema: crog_acquisition; Owner: -
--

CREATE TABLE crog_acquisition.owner_contacts (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    owner_id uuid NOT NULL,
    contact_type character varying(50),
    contact_value character varying(255) NOT NULL,
    source character varying(100),
    confidence_score numeric(3,2),
    is_dnc boolean DEFAULT false NOT NULL,
    CONSTRAINT ck_acquisition_owner_contacts_confidence_score CHECK (((confidence_score >= 0.00) AND (confidence_score <= 1.00))),
    CONSTRAINT ck_acquisition_owner_contacts_contact_type CHECK (((contact_type)::text = ANY (ARRAY[('CELL'::character varying)::text, ('LANDLINE'::character varying)::text, ('EMAIL'::character varying)::text])))
);


--
-- Name: owners; Type: TABLE; Schema: crog_acquisition; Owner: -
--

CREATE TABLE crog_acquisition.owners (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    legal_name character varying(255) NOT NULL,
    tax_mailing_address text NOT NULL,
    primary_residence_state character varying(2),
    psychological_profile jsonb,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: parcels; Type: TABLE; Schema: crog_acquisition; Owner: -
--

CREATE TABLE crog_acquisition.parcels (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    county_name character varying(100) DEFAULT 'Fannin'::character varying NOT NULL,
    parcel_id character varying(100) NOT NULL,
    geom text,
    assessed_value numeric(12,2) NOT NULL,
    zoning_code character varying(50),
    is_waterfront boolean DEFAULT false NOT NULL,
    is_ridgeline boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: properties; Type: TABLE; Schema: crog_acquisition; Owner: -
--

CREATE TABLE crog_acquisition.properties (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    parcel_id uuid NOT NULL,
    owner_id uuid,
    fannin_str_cert_id character varying(100),
    blue_ridge_str_permit character varying(100),
    zillow_zpid character varying(100),
    google_place_id character varying(255),
    airbnb_listing_id character varying(100),
    vrbo_listing_id character varying(100),
    status crog_acquisition.market_state DEFAULT 'UNMANAGED'::crog_acquisition.market_state NOT NULL,
    management_company character varying(255),
    bedrooms integer,
    bathrooms numeric(3,1),
    projected_adr numeric(8,2),
    projected_annual_revenue numeric(10,2),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: str_signals; Type: TABLE; Schema: crog_acquisition; Owner: -
--

CREATE TABLE crog_acquisition.str_signals (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    property_id uuid NOT NULL,
    signal_source crog_acquisition.signal_source NOT NULL,
    confidence_score numeric(3,2) NOT NULL,
    raw_payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    detected_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT ck_acquisition_str_signals_confidence_score CHECK (((confidence_score >= 0.00) AND (confidence_score <= 1.00)))
);


--
-- Name: device_events; Type: TABLE; Schema: iot_schema; Owner: -
--

CREATE TABLE iot_schema.device_events (
    id uuid NOT NULL,
    device_id character varying(100) NOT NULL,
    event_type character varying(100) NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: digital_twins; Type: TABLE; Schema: iot_schema; Owner: -
--

CREATE TABLE iot_schema.digital_twins (
    id uuid NOT NULL,
    device_id character varying(100) NOT NULL,
    property_id character varying(100) NOT NULL,
    device_type character varying(50) NOT NULL,
    device_name character varying(255),
    state_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    battery_level integer,
    is_online boolean,
    last_event_ts timestamp with time zone DEFAULT now(),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: ai_audit_ledger; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.ai_audit_ledger (
    id integer NOT NULL,
    case_slug text,
    prompt_hash text,
    retrieved_vectors jsonb DEFAULT '[]'::jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: ai_audit_ledger_id_seq; Type: SEQUENCE; Schema: legal; Owner: -
--

CREATE SEQUENCE legal.ai_audit_ledger_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ai_audit_ledger_id_seq; Type: SEQUENCE OWNED BY; Schema: legal; Owner: -
--

ALTER SEQUENCE legal.ai_audit_ledger_id_seq OWNED BY legal.ai_audit_ledger.id;


--
-- Name: case_evidence; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.case_evidence (
    id uuid NOT NULL,
    case_slug character varying(255) NOT NULL,
    entity_id uuid,
    file_name character varying(500) NOT NULL,
    nas_path text NOT NULL,
    qdrant_point_id character varying(255),
    sha256_hash character varying(128) NOT NULL,
    uploaded_at timestamp with time zone NOT NULL
);


--
-- Name: case_graph_edges; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.case_graph_edges (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    case_id uuid NOT NULL,
    source_node_id uuid NOT NULL,
    target_node_id uuid NOT NULL,
    relationship_type character varying(128) NOT NULL,
    weight double precision DEFAULT 1.0 NOT NULL,
    source_ref character varying(500),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: case_graph_edges_v2; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.case_graph_edges_v2 (
    id uuid NOT NULL,
    case_slug character varying(255) NOT NULL,
    source_node_id uuid NOT NULL,
    target_node_id uuid NOT NULL,
    relationship_type character varying(128) NOT NULL,
    weight double precision NOT NULL,
    source_evidence_id uuid
);


--
-- Name: case_graph_nodes; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.case_graph_nodes (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    case_id uuid NOT NULL,
    entity_type character varying(64) NOT NULL,
    label character varying(500) NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: case_graph_nodes_v2; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.case_graph_nodes_v2 (
    id uuid NOT NULL,
    case_slug character varying(255) NOT NULL,
    entity_type character varying(64) NOT NULL,
    entity_reference_id uuid,
    label character varying(500) NOT NULL,
    properties_json jsonb NOT NULL
);


--
-- Name: case_statements; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.case_statements (
    id integer NOT NULL,
    case_slug text NOT NULL,
    entity_name text,
    quote_text text,
    source_ref text,
    stated_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: case_statements_id_seq; Type: SEQUENCE; Schema: legal; Owner: -
--

CREATE SEQUENCE legal.case_statements_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: case_statements_id_seq; Type: SEQUENCE OWNED BY; Schema: legal; Owner: -
--

ALTER SEQUENCE legal.case_statements_id_seq OWNED BY legal.case_statements.id;


--
-- Name: case_statements_v2; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.case_statements_v2 (
    id uuid NOT NULL,
    case_slug character varying(255) NOT NULL,
    entity_id uuid,
    quote_text text NOT NULL,
    source_ref text,
    doc_id character varying(255),
    stated_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: cases; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.cases (
    id integer NOT NULL,
    case_slug text NOT NULL,
    case_number text,
    case_name text,
    court text,
    judge text,
    case_type text DEFAULT 'civil'::text,
    our_role text DEFAULT 'creditor'::text,
    status text DEFAULT 'active'::text,
    extracted_entities jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: cases_id_seq; Type: SEQUENCE; Schema: legal; Owner: -
--

CREATE SEQUENCE legal.cases_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cases_id_seq; Type: SEQUENCE OWNED BY; Schema: legal; Owner: -
--

ALTER SEQUENCE legal.cases_id_seq OWNED BY legal.cases.id;


--
-- Name: deposition_kill_sheets_v2; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.deposition_kill_sheets_v2 (
    id uuid NOT NULL,
    case_slug character varying(255) NOT NULL,
    deponent_entity character varying(255) NOT NULL,
    status character varying(32) NOT NULL,
    summary text NOT NULL,
    high_risk_topics_json jsonb NOT NULL,
    document_sequence_json jsonb NOT NULL,
    suggested_questions_json jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: discovery_draft_items_v2; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.discovery_draft_items_v2 (
    id uuid NOT NULL,
    pack_id uuid NOT NULL,
    category character varying(32) NOT NULL,
    content text NOT NULL,
    rationale_from_graph text NOT NULL,
    sequence_number integer NOT NULL,
    lethality_score integer,
    proportionality_score integer,
    correction_notes character varying(2000)
);


--
-- Name: discovery_draft_packs_v2; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.discovery_draft_packs_v2 (
    id uuid NOT NULL,
    case_slug character varying(255) NOT NULL,
    target_entity character varying(255) NOT NULL,
    status character varying(32) NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: distillation_memory; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.distillation_memory (
    id uuid NOT NULL,
    context_hash character varying(128) NOT NULL,
    frontier_insight text NOT NULL,
    local_correction text NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: entities; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.entities (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    type character varying(100) NOT NULL,
    role character varying(100)
);


--
-- Name: event_log; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.event_log (
    id bigint NOT NULL,
    event_type text NOT NULL,
    case_slug text,
    event_payload jsonb NOT NULL,
    emitted_at timestamp with time zone DEFAULT now() NOT NULL,
    emitted_by text NOT NULL,
    processed_at timestamp with time zone,
    processed_by text,
    result jsonb,
    CONSTRAINT chk_event_log_emitted_by_format CHECK ((emitted_by ~ '^[a-z_]+:[a-z0-9_.-]+$'::text))
);


--
-- Name: event_log_id_seq; Type: SEQUENCE; Schema: legal; Owner: -
--

CREATE SEQUENCE legal.event_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: event_log_id_seq; Type: SEQUENCE OWNED BY; Schema: legal; Owner: -
--

ALTER SEQUENCE legal.event_log_id_seq OWNED BY legal.event_log.id;


--
-- Name: legal_cases; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.legal_cases (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    slug character varying(255) NOT NULL,
    court character varying(255) DEFAULT ''::character varying NOT NULL,
    jurisdiction character varying(255) DEFAULT ''::character varying NOT NULL,
    status character varying(64) DEFAULT 'open'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: legal_exemplars; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.legal_exemplars (
    id uuid NOT NULL,
    category character varying(32) NOT NULL,
    rationale_context text NOT NULL,
    perfect_output text NOT NULL,
    source_model character varying(128) NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: mail_ingester_metrics; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.mail_ingester_metrics (
    id bigint NOT NULL,
    metric_name text NOT NULL,
    mailbox_alias text,
    label_key text,
    label_value text,
    counter_value bigint DEFAULT 0 NOT NULL,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: mail_ingester_metrics_id_seq; Type: SEQUENCE; Schema: legal; Owner: -
--

CREATE SEQUENCE legal.mail_ingester_metrics_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: mail_ingester_metrics_id_seq; Type: SEQUENCE OWNED BY; Schema: legal; Owner: -
--

ALTER SEQUENCE legal.mail_ingester_metrics_id_seq OWNED BY legal.mail_ingester_metrics.id;


--
-- Name: mail_ingester_pause; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.mail_ingester_pause (
    mailbox_alias text NOT NULL,
    paused_at timestamp with time zone DEFAULT now() NOT NULL,
    paused_by text NOT NULL,
    reason text
);


--
-- Name: mail_ingester_state; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.mail_ingester_state (
    mailbox_alias text NOT NULL,
    last_patrol_at timestamp with time zone,
    last_success_at timestamp with time zone,
    last_error_at timestamp with time zone,
    last_error text,
    messages_ingested_total bigint DEFAULT 0 NOT NULL,
    messages_deduped_total bigint DEFAULT 0 NOT NULL,
    messages_errored_total bigint DEFAULT 0 NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: priority_sender_rules; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.priority_sender_rules (
    id bigint NOT NULL,
    sender_pattern text NOT NULL,
    priority text NOT NULL,
    case_slug text,
    rationale text,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT chk_priority_sender_priority CHECK ((priority = ANY (ARRAY['P1'::text, 'P2'::text, 'P3'::text])))
);


--
-- Name: priority_sender_rules_id_seq; Type: SEQUENCE; Schema: legal; Owner: -
--

CREATE SEQUENCE legal.priority_sender_rules_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: priority_sender_rules_id_seq; Type: SEQUENCE OWNED BY; Schema: legal; Owner: -
--

ALTER SEQUENCE legal.priority_sender_rules_id_seq OWNED BY legal.priority_sender_rules.id;


--
-- Name: sanctions_alerts_v2; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.sanctions_alerts_v2 (
    id uuid NOT NULL,
    case_slug character varying(255) NOT NULL,
    alert_type character varying(32) NOT NULL,
    contradiction_summary text NOT NULL,
    confidence_score integer NOT NULL,
    status character varying(32) NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: sanctions_tripwire_runs_v2; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.sanctions_tripwire_runs_v2 (
    id uuid NOT NULL,
    case_slug character varying(255) NOT NULL,
    trigger_source character varying(64) NOT NULL,
    status character varying(32) NOT NULL,
    model_used character varying(128),
    alerts_found integer NOT NULL,
    alerts_saved integer NOT NULL,
    error_detail text,
    started_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone
);


--
-- Name: timeline_events; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.timeline_events (
    id uuid NOT NULL,
    case_slug character varying(255) NOT NULL,
    event_date date NOT NULL,
    description text NOT NULL,
    source_evidence_id uuid
);


--
-- Name: vault_documents; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.vault_documents (
    id integer NOT NULL,
    case_slug text NOT NULL,
    file_name text,
    nfs_path text,
    mime_type text,
    chunk_count integer,
    processing_status text DEFAULT 'pending'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: vault_documents_id_seq; Type: SEQUENCE; Schema: legal; Owner: -
--

CREATE SEQUENCE legal.vault_documents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vault_documents_id_seq; Type: SEQUENCE OWNED BY; Schema: legal; Owner: -
--

ALTER SEQUENCE legal.vault_documents_id_seq OWNED BY legal.vault_documents.id;


--
-- Name: accounts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.accounts (
    id bigint NOT NULL,
    code character varying(32) NOT NULL,
    name character varying(255) NOT NULL
);


--
-- Name: accounts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.accounts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: accounts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.accounts_id_seq OWNED BY public.accounts.id;


--
-- Name: activities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.activities (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    title character varying(500) NOT NULL,
    slug character varying(255) NOT NULL,
    activity_slug character varying(500),
    body text,
    body_summary text,
    address text,
    activity_type character varying(255),
    activity_type_tid integer,
    area character varying(255),
    area_tid integer,
    people character varying(255),
    people_tid integer,
    difficulty_level character varying(255),
    difficulty_level_tid integer,
    season character varying(255),
    season_tid integer,
    featured_image_url text,
    featured_image_alt character varying(500),
    featured_image_title character varying(500),
    video_urls jsonb,
    latitude double precision,
    longitude double precision,
    status character varying(50) DEFAULT 'published'::character varying,
    is_featured boolean DEFAULT false,
    display_order integer DEFAULT 0,
    drupal_nid integer,
    drupal_vid integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    published_at timestamp with time zone
);


--
-- Name: agent_queue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_queue (
    id uuid NOT NULL,
    guest_id uuid,
    property_id uuid,
    original_ai_draft text NOT NULL,
    final_human_message text,
    status character varying(30) NOT NULL,
    delivery_channel character varying(20) DEFAULT 'email'::character varying NOT NULL,
    twilio_sid character varying(128),
    error_log text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_agent_queue_status CHECK (((status)::text = ANY (ARRAY[('pending_review'::character varying)::text, ('approved'::character varying)::text, ('edited'::character varying)::text, ('rejected'::character varying)::text, ('sending'::character varying)::text, ('delivered'::character varying)::text, ('failed'::character varying)::text])))
);


--
-- Name: agent_registry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_registry (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    role character varying(100) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    scope_boundary jsonb NOT NULL,
    daily_tool_budget integer NOT NULL,
    CONSTRAINT ck_agent_registry_daily_tool_budget_nonnegative CHECK ((daily_tool_budget >= 0))
);


--
-- Name: agent_response_queue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_response_queue (
    id uuid NOT NULL,
    message_id uuid NOT NULL,
    guest_id uuid,
    reservation_id uuid,
    intent character varying(50),
    sentiment_label character varying(30),
    sentiment_score double precision,
    urgency_level integer,
    proposed_response text NOT NULL,
    confidence double precision NOT NULL,
    action character varying(80),
    escalation_reason text,
    status character varying(30) NOT NULL,
    reviewed_by character varying(100),
    reviewed_at timestamp without time zone,
    final_response text,
    sent_message_id uuid,
    decision_metadata jsonb,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


--
-- Name: agent_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_runs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    agent_id uuid NOT NULL,
    trigger_source character varying(100) NOT NULL,
    status character varying(9) DEFAULT 'queued'::character varying NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    CONSTRAINT agent_run_status CHECK (((status)::text = ANY (ARRAY[('queued'::character varying)::text, ('running'::character varying)::text, ('completed'::character varying)::text, ('failed'::character varying)::text, ('escalated'::character varying)::text, ('blocked'::character varying)::text])))
);


--
-- Name: agreement_templates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agreement_templates (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    agreement_type character varying(50) NOT NULL,
    content_markdown text NOT NULL,
    required_variables jsonb,
    is_active boolean,
    requires_signature boolean,
    requires_initials boolean,
    auto_send boolean,
    send_days_before_checkin integer,
    property_ids jsonb,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: analytics_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.analytics_events (
    id uuid NOT NULL,
    event_type character varying(100) NOT NULL,
    guest_id uuid,
    reservation_id uuid,
    property_id uuid,
    event_data jsonb,
    session_id uuid,
    user_agent text,
    ip_address inet,
    created_at timestamp without time zone
);


--
-- Name: async_job_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.async_job_runs (
    id uuid NOT NULL,
    job_name character varying(100) NOT NULL,
    queue_name character varying(100) NOT NULL,
    status character varying(20) NOT NULL,
    requested_by character varying(255),
    tenant_id character varying(100),
    request_id character varying(100),
    arq_job_id character varying(100),
    attempts integer NOT NULL,
    payload_json jsonb NOT NULL,
    result_json jsonb NOT NULL,
    error_text text,
    created_at timestamp with time zone NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_async_job_runs_status CHECK (((status)::text = ANY (ARRAY[('queued'::character varying)::text, ('running'::character varying)::text, ('succeeded'::character varying)::text, ('failed'::character varying)::text, ('cancelled'::character varying)::text])))
);


--
-- Name: blocked_days; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.blocked_days (
    id uuid NOT NULL,
    property_id uuid NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    block_type character varying(50),
    confirmation_code character varying(50),
    source character varying(20),
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


--
-- Name: blogs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.blogs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    title character varying(500) NOT NULL,
    slug character varying(255) NOT NULL,
    body text,
    author_name character varying(255),
    status character varying(50) DEFAULT 'published'::character varying,
    is_promoted boolean DEFAULT false,
    is_sticky boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    published_at timestamp with time zone
);


--
-- Name: capex_staging; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.capex_staging (
    id bigint NOT NULL,
    property_id character varying(100) NOT NULL,
    vendor character varying(255) NOT NULL,
    amount numeric(12,2) NOT NULL,
    total_owner_charge numeric(12,2) NOT NULL,
    description text,
    journal_lines jsonb,
    audit_trail jsonb,
    compliance_status character varying(64) DEFAULT 'PENDING_CAPEX_APPROVAL'::character varying NOT NULL,
    approved_by character varying(100),
    approved_at timestamp with time zone,
    rejected_by character varying(100),
    rejected_at timestamp with time zone,
    rejection_reason text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: capex_staging_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.capex_staging_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: capex_staging_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.capex_staging_id_seq OWNED BY public.capex_staging.id;


--
-- Name: capture_labels; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.capture_labels (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    capture_id uuid NOT NULL,
    capture_table character varying(32) NOT NULL,
    task_type character varying(64) NOT NULL,
    godhead_model character varying(128),
    godhead_decision character varying(16),
    godhead_reasoning text,
    godhead_called_at timestamp with time zone,
    godhead_cost_usd numeric(8,4),
    qc_sampled boolean DEFAULT false NOT NULL,
    qc_decision character varying(16),
    qc_note text,
    qc_reviewed_at timestamp with time zone,
    final_decision character varying(16),
    label_source character varying(16)
);


--
-- Name: channel_mappings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.channel_mappings (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    property_id uuid NOT NULL,
    channel character varying(50) NOT NULL,
    external_listing_id character varying(255) NOT NULL,
    sync_status character varying(30) DEFAULT 'active'::character varying NOT NULL,
    last_synced_at timestamp with time zone,
    sync_error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: citation_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.citation_records (
    id uuid NOT NULL,
    directory_domain character varying(255) NOT NULL,
    profile_url character varying(1000),
    found_name character varying(500),
    found_address character varying(1000),
    found_phone character varying(100),
    match_status character varying(30) NOT NULL,
    last_audited_at timestamp without time zone NOT NULL
);


--
-- Name: cleaners; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cleaners (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(200) NOT NULL,
    phone character varying(40),
    email character varying(255),
    active boolean DEFAULT true NOT NULL,
    per_clean_rate numeric(8,2),
    hourly_rate numeric(8,2),
    property_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    regions jsonb DEFAULT '[]'::jsonb NOT NULL,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: competitor_listings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.competitor_listings (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    property_id uuid NOT NULL,
    platform character varying(11) NOT NULL,
    external_url character varying(500),
    external_id character varying(100),
    dedupe_hash character varying(64) NOT NULL,
    observed_nightly_rate numeric(12,2) NOT NULL,
    observed_total_before_tax numeric(12,2) NOT NULL,
    platform_fee numeric(12,2) DEFAULT 0 NOT NULL,
    cleaning_fee numeric(12,2) DEFAULT 0 NOT NULL,
    total_after_tax numeric(12,2) NOT NULL,
    snapshot_payload jsonb NOT NULL,
    last_observed timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ota_provider CHECK (((platform)::text = ANY (ARRAY[('airbnb'::character varying)::text, ('vrbo'::character varying)::text, ('booking_com'::character varying)::text])))
);


--
-- Name: concierge_queue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.concierge_queue (
    id uuid NOT NULL,
    guest_phone character varying(40) NOT NULL,
    property_id uuid,
    inbound_message text NOT NULL,
    retrieved_context jsonb NOT NULL,
    ai_draft_reply text,
    reviewed_by character varying(120),
    review_note text,
    sent_at timestamp without time zone,
    metadata_json jsonb NOT NULL,
    status character varying(30) NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    CONSTRAINT ck_concierge_queue_status CHECK (((status)::text = ANY (ARRAY[('pending_review'::character varying)::text, ('approved'::character varying)::text, ('rejected'::character varying)::text, ('sent'::character varying)::text, ('failed'::character varying)::text])))
);


--
-- Name: concierge_recovery_dispatches; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.concierge_recovery_dispatches (
    id uuid NOT NULL,
    session_fp character varying(64),
    guest_id uuid NOT NULL,
    channel character varying(16) NOT NULL,
    template_key character varying(64) DEFAULT 'abandon_cart_v1'::character varying NOT NULL,
    body_preview text,
    status character varying(24) DEFAULT 'sent'::character varying NOT NULL,
    provider_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: damage_claims; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.damage_claims (
    id uuid NOT NULL,
    claim_number character varying(50) NOT NULL,
    reservation_id uuid NOT NULL,
    property_id uuid NOT NULL,
    guest_id uuid NOT NULL,
    damage_description text NOT NULL,
    policy_violations text,
    damage_areas text[],
    estimated_cost numeric(10,2),
    photo_urls text[],
    reported_by character varying(200) NOT NULL,
    inspection_date date NOT NULL,
    inspection_notes text,
    legal_draft text,
    legal_draft_model character varying(100),
    legal_draft_at timestamp without time zone,
    rental_agreement_id uuid,
    agreement_clauses jsonb,
    status character varying(30) NOT NULL,
    reviewed_by character varying(200),
    reviewed_at timestamp without time zone,
    final_response text,
    sent_at timestamp without time zone,
    sent_via character varying(30),
    resolution text,
    resolution_amount numeric(10,2),
    resolved_at timestamp without time zone,
    qdrant_point_id uuid,
    created_at timestamp without time zone,
    updated_at timestamp without time zone,
    stripe_charge_id character varying(255),
    amount_charged numeric(10,2),
    charge_payment_method_id character varying(255),
    charge_executed_at timestamp with time zone,
    charge_executed_by character varying(255)
);


--
-- Name: deferred_api_writes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.deferred_api_writes (
    id bigint NOT NULL,
    service character varying(128) NOT NULL,
    method character varying(512) NOT NULL,
    payload jsonb NOT NULL,
    status character varying(64) DEFAULT 'pending'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    retry_count integer DEFAULT 0 NOT NULL,
    last_error text,
    reconciled_at timestamp with time zone
);


--
-- Name: deferred_api_writes_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.deferred_api_writes_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: deferred_api_writes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.deferred_api_writes_id_seq OWNED BY public.deferred_api_writes.id;


--
-- Name: distillation_queue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.distillation_queue (
    id uuid NOT NULL,
    source_module character varying(120) NOT NULL,
    source_ref character varying(255) NOT NULL,
    source_intelligence_id uuid,
    input_payload jsonb NOT NULL,
    output_payload jsonb NOT NULL,
    status character varying(10) NOT NULL,
    error text,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


--
-- Name: email_inquirers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.email_inquirers (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    email character varying(255) NOT NULL,
    display_name character varying(255),
    first_name character varying(100),
    last_name character varying(100),
    guest_id uuid,
    inferred_party_size integer,
    inferred_dates_text text,
    opt_in_email boolean DEFAULT true NOT NULL,
    first_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    last_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    inquiry_count integer DEFAULT 1 NOT NULL
);


--
-- Name: email_messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.email_messages (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    inquirer_id uuid NOT NULL,
    guest_id uuid,
    reservation_id uuid,
    in_reply_to_message_id uuid,
    direction character varying(20) NOT NULL,
    email_from character varying(255) NOT NULL,
    email_to character varying(255) NOT NULL,
    email_cc text,
    subject text,
    body_text text NOT NULL,
    body_excerpt text,
    imap_uid bigint,
    imap_message_id text,
    received_at timestamp with time zone,
    intent character varying(50),
    sentiment character varying(20),
    category character varying(50),
    ai_draft text,
    ai_confidence numeric(4,3),
    ai_meta jsonb,
    approval_status character varying(30) DEFAULT 'pending_approval'::character varying NOT NULL,
    requires_human_review boolean DEFAULT true NOT NULL,
    human_reviewed_at timestamp with time zone,
    human_reviewed_by uuid,
    human_edited_body text,
    sent_at timestamp with time zone,
    smtp_message_id text,
    error_code character varying(50),
    error_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    extra_data jsonb,
    has_attachments boolean DEFAULT false NOT NULL,
    image_descriptions jsonb,
    CONSTRAINT ck_email_messages_approval_status CHECK (((approval_status)::text = ANY (ARRAY[('pending_approval'::character varying)::text, ('approved'::character varying)::text, ('rejected'::character varying)::text, ('sent'::character varying)::text, ('send_failed'::character varying)::text, ('no_draft_needed'::character varying)::text]))),
    CONSTRAINT ck_email_messages_direction CHECK (((direction)::text = ANY (ARRAY[('inbound'::character varying)::text, ('outbound'::character varying)::text])))
);


--
-- Name: email_templates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.email_templates (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    trigger_event character varying(100) NOT NULL,
    subject_template character varying(1000) NOT NULL,
    body_template text NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    requires_human_approval boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


--
-- Name: extra_orders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.extra_orders (
    id uuid NOT NULL,
    reservation_id uuid NOT NULL,
    extra_id uuid NOT NULL,
    quantity integer,
    unit_price numeric(10,2) NOT NULL,
    total_price numeric(10,2) NOT NULL,
    status character varying(50) NOT NULL,
    fulfilled_at timestamp without time zone,
    notes text,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


--
-- Name: extras; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.extras (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    category character varying(50),
    price numeric(10,2) NOT NULL,
    currency character varying(3),
    is_available boolean,
    properties uuid[],
    image_url text,
    display_order integer,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


--
-- Name: fees; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fees (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    flat_amount numeric(12,2) NOT NULL,
    is_pet_fee boolean DEFAULT false NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    fee_type character varying(20) DEFAULT 'flat'::character varying NOT NULL,
    percentage_rate numeric(6,3),
    is_optional boolean DEFAULT false NOT NULL
);


--
-- Name: financial_approvals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.financial_approvals (
    id uuid NOT NULL,
    reservation_id character varying(100) NOT NULL,
    status character varying(30) DEFAULT 'pending'::character varying NOT NULL,
    discrepancy_type character varying(100) NOT NULL,
    local_total_cents integer NOT NULL,
    streamline_total_cents integer NOT NULL,
    delta_cents integer NOT NULL,
    context_payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    resolution_strategy character varying(30),
    stripe_invoice_id character varying(255),
    resolved_by character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    resolved_at timestamp with time zone
);


--
-- Name: functional_nodes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.functional_nodes (
    id uuid NOT NULL,
    legacy_node_id integer,
    source_path character varying(255) NOT NULL,
    canonical_path character varying(512) NOT NULL,
    title character varying(255) NOT NULL,
    node_type character varying(64) NOT NULL,
    content_category character varying(64) NOT NULL,
    functional_complexity character varying(64) NOT NULL,
    crawl_status character varying(32) NOT NULL,
    mirror_status character varying(32) NOT NULL,
    cutover_status character varying(32) NOT NULL,
    priority_tier integer NOT NULL,
    is_published boolean NOT NULL,
    http_status integer,
    body_html text,
    body_text_preview text,
    form_fields jsonb NOT NULL,
    taxonomy_terms jsonb NOT NULL,
    media_refs jsonb NOT NULL,
    source_metadata jsonb NOT NULL,
    mirror_component_path character varying(512),
    mirror_route_path character varying(512),
    source_hash character varying(64),
    last_crawled_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: guest_activities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.guest_activities (
    id uuid NOT NULL,
    guest_id uuid NOT NULL,
    activity_type character varying(50) NOT NULL,
    category character varying(30) NOT NULL,
    title character varying(255) NOT NULL,
    description text,
    reservation_id uuid,
    property_id uuid,
    message_id uuid,
    review_id uuid,
    survey_id uuid,
    agreement_id uuid,
    work_order_id uuid,
    performed_by character varying(100),
    performed_by_type character varying(20),
    metadata jsonb,
    importance character varying(10),
    is_visible_to_guest character varying(5),
    created_at timestamp without time zone
);


--
-- Name: guest_quotes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.guest_quotes (
    id uuid NOT NULL,
    target_property_id character varying(255) NOT NULL,
    property_id uuid,
    status public.guest_quote_status NOT NULL,
    campaign character varying(100) NOT NULL,
    target_keyword character varying(255),
    guest_name character varying(255),
    guest_email character varying(255),
    guest_phone character varying(40),
    check_in date,
    check_out date,
    nights integer,
    adults integer NOT NULL,
    children integer NOT NULL,
    pets integer NOT NULL,
    currency character varying(10) NOT NULL,
    base_rent numeric(12,2) NOT NULL,
    taxes numeric(12,2) NOT NULL,
    fees numeric(12,2) NOT NULL,
    total_amount numeric(12,2) NOT NULL,
    base_price double precision NOT NULL,
    ai_adjusted_price double precision NOT NULL,
    sovereign_narrative text NOT NULL,
    quote_breakdown jsonb NOT NULL,
    source_snapshot jsonb NOT NULL,
    stripe_payment_link_url character varying(1024),
    stripe_payment_link_id character varying(255),
    note text,
    expires_at timestamp without time zone NOT NULL,
    accepted_at timestamp without time zone,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


--
-- Name: guest_reviews; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.guest_reviews (
    id uuid NOT NULL,
    guest_id uuid NOT NULL,
    reservation_id uuid,
    property_id uuid NOT NULL,
    direction character varying(30) NOT NULL,
    overall_rating integer NOT NULL,
    cleanliness_rating integer,
    accuracy_rating integer,
    communication_rating integer,
    location_rating integer,
    checkin_rating integer,
    value_rating integer,
    amenities_rating integer,
    house_rules_rating integer,
    cleanliness_left_rating integer,
    communication_guest_rating integer,
    respect_rating integer,
    noise_rating integer,
    checkout_compliance_rating integer,
    title character varying(255),
    body text,
    response_body text,
    response_by character varying(100),
    response_at timestamp without time zone,
    sentiment character varying(20),
    sentiment_score numeric(4,3),
    key_phrases jsonb,
    improvement_suggestions jsonb,
    is_published boolean,
    published_at timestamp without time zone,
    publish_to_website boolean,
    publish_to_airbnb boolean,
    publish_to_google boolean,
    external_review_urls jsonb,
    is_flagged boolean,
    flag_reason character varying(255),
    moderated_by character varying(100),
    moderated_at timestamp without time zone,
    solicitation_sent_at timestamp without time zone,
    solicitation_method character varying(20),
    solicitation_template_id uuid,
    submitted_via character varying(30),
    streamline_feedback_id character varying(100),
    source character varying(50),
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


--
-- Name: guest_surveys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.guest_surveys (
    id uuid NOT NULL,
    guest_id uuid NOT NULL,
    reservation_id uuid,
    property_id uuid,
    template_id uuid,
    survey_type character varying(50) NOT NULL,
    responses jsonb NOT NULL,
    overall_score numeric(4,2),
    nps_score integer,
    nps_category character varying(20),
    housekeeping_score integer,
    maintenance_score integer,
    communication_score integer,
    amenities_score integer,
    sentiment character varying(20),
    key_themes jsonb,
    action_items jsonb,
    status character varying(30) NOT NULL,
    sent_at timestamp without time zone,
    started_at timestamp without time zone,
    completed_at timestamp without time zone,
    send_method character varying(20),
    survey_url text,
    follow_up_required boolean,
    follow_up_notes text,
    follow_up_completed_at timestamp without time zone,
    follow_up_by character varying(100),
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


--
-- Name: guest_verifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.guest_verifications (
    id uuid NOT NULL,
    guest_id uuid NOT NULL,
    reservation_id uuid,
    verification_type character varying(50) NOT NULL,
    status character varying(30) NOT NULL,
    document_type character varying(50),
    document_number_hash character varying(255),
    document_country character varying(2),
    document_state character varying(5),
    document_expiration date,
    document_front_url text,
    document_back_url text,
    selfie_url text,
    confidence_score numeric(4,3),
    match_details jsonb,
    reviewed_by character varying(100),
    reviewed_at timestamp without time zone,
    rejection_reason text,
    external_verification_id character varying(255),
    provider character varying(50),
    ip_address character varying(45),
    user_agent text,
    created_at timestamp without time zone,
    updated_at timestamp without time zone,
    expires_at timestamp without time zone
);


--
-- Name: guestbook_guides; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.guestbook_guides (
    id uuid NOT NULL,
    property_id uuid,
    title character varying(255) NOT NULL,
    slug character varying(255) NOT NULL,
    guide_type character varying(50) NOT NULL,
    category character varying(50),
    content text NOT NULL,
    icon character varying(50),
    display_order integer,
    is_visible boolean,
    visibility_rules jsonb,
    view_count integer,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


--
-- Name: guests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.guests (
    id uuid NOT NULL,
    phone character varying(20) NOT NULL,
    phone_number_secondary character varying(20),
    email character varying(255),
    email_secondary character varying(255),
    first_name character varying(100),
    last_name character varying(100),
    address_line1 character varying(255),
    address_line2 character varying(255),
    city character varying(100),
    state character varying(50),
    postal_code character varying(20),
    country character varying(2),
    date_of_birth date,
    emergency_contact_name character varying(200),
    emergency_contact_phone character varying(20),
    emergency_contact_relationship character varying(50),
    vehicle_make character varying(50),
    vehicle_model character varying(50),
    vehicle_color character varying(30),
    vehicle_plate character varying(20),
    vehicle_state character varying(5),
    language_preference character varying(10),
    opt_in_marketing boolean,
    opt_in_sms boolean,
    opt_in_email boolean,
    preferred_contact_method character varying(20),
    quiet_hours_start character varying(5),
    quiet_hours_end character varying(5),
    timezone character varying(50),
    verification_status character varying(20),
    verification_method character varying(50),
    verified_at timestamp without time zone,
    id_document_type character varying(50),
    id_expiration_date date,
    loyalty_tier character varying(20),
    loyalty_points integer,
    loyalty_enrolled_at timestamp without time zone,
    lifetime_stays integer,
    lifetime_nights integer,
    lifetime_revenue numeric(12,2),
    value_score integer,
    risk_score integer,
    satisfaction_score integer,
    preferences jsonb,
    special_requests text,
    internal_notes text,
    staff_notes text,
    is_vip boolean,
    is_blacklisted boolean,
    blacklist_reason text,
    blacklisted_at timestamp without time zone,
    blacklisted_by character varying(100),
    is_do_not_contact boolean,
    requires_supervision boolean,
    guest_source character varying(50),
    referral_source character varying(255),
    first_booking_source character varying(50),
    acquisition_campaign character varying(100),
    total_stays integer,
    total_messages_sent integer,
    total_messages_received integer,
    average_rating numeric(3,2),
    last_stay_date date,
    streamline_guest_id character varying(100),
    airbnb_guest_id character varying(100),
    vrbo_guest_id character varying(100),
    booking_com_guest_id character varying(100),
    stripe_customer_id character varying(100),
    tags character varying[],
    notes text,
    created_at timestamp without time zone,
    updated_at timestamp without time zone,
    last_contacted_at timestamp without time zone,
    last_activity_at timestamp without time zone
);


--
-- Name: housekeeping_tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.housekeeping_tasks (
    id uuid NOT NULL,
    property_id uuid NOT NULL,
    reservation_id uuid,
    scheduled_date date NOT NULL,
    scheduled_time time without time zone,
    status character varying(20) NOT NULL,
    assigned_to character varying(255),
    cleaning_type character varying(20) NOT NULL,
    estimated_minutes integer,
    actual_minutes integer,
    notes text,
    completed_at timestamp without time zone,
    streamline_source jsonb,
    streamline_synced_at timestamp without time zone,
    streamline_checklist_id character varying(100),
    dispatched_by character varying(50),
    dispatch_payload jsonb,
    created_at timestamp without time zone,
    legacy_assigned_to character varying(255),
    assigned_cleaner_id uuid
);


--
-- Name: hunter_queue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.hunter_queue (
    id uuid NOT NULL,
    session_fp character varying(128) NOT NULL,
    property_id uuid,
    reservation_id uuid,
    guest_phone character varying(40),
    guest_email character varying(255),
    campaign character varying(120) NOT NULL,
    payload jsonb NOT NULL,
    score integer NOT NULL,
    status character varying(30) NOT NULL,
    last_error text,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    CONSTRAINT ck_hunter_queue_status CHECK (((status)::text = ANY (ARRAY[('queued'::character varying)::text, ('processing'::character varying)::text, ('sent'::character varying)::text, ('failed'::character varying)::text, ('cancelled'::character varying)::text])))
);


--
-- Name: hunter_recovery_ops; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.hunter_recovery_ops (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    cart_id character varying(255) NOT NULL,
    guest_name character varying(255),
    cabin_name character varying(255),
    cart_value numeric(10,2),
    status public.hunter_recovery_op_status DEFAULT 'QUEUED'::public.hunter_recovery_op_status NOT NULL,
    ai_draft_body text,
    assigned_worker character varying(32),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: hunter_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.hunter_runs (
    id uuid NOT NULL,
    trigger character varying(120) NOT NULL,
    campaign character varying(120) NOT NULL,
    stats jsonb NOT NULL,
    started_at timestamp without time zone NOT NULL,
    completed_at timestamp without time zone
);


--
-- Name: intelligence_ledger; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.intelligence_ledger (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    category character varying(64) NOT NULL,
    title character varying(255) NOT NULL,
    summary text NOT NULL,
    market character varying(128) NOT NULL,
    locality character varying(128),
    dedupe_hash character varying(64) NOT NULL,
    confidence_score double precision,
    query_topic character varying(120),
    scout_query text,
    scout_run_key character varying(120),
    target_property_ids jsonb NOT NULL,
    target_tags jsonb NOT NULL,
    source_urls jsonb NOT NULL,
    grounding_payload jsonb NOT NULL,
    finding_payload jsonb NOT NULL,
    discovered_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: journal_entries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.journal_entries (
    id bigint NOT NULL,
    property_id character varying(100) NOT NULL,
    entry_date date DEFAULT CURRENT_DATE NOT NULL,
    description text,
    reference_type character varying(64) NOT NULL,
    reference_id character varying(255) NOT NULL,
    is_void boolean DEFAULT false NOT NULL,
    posted_by character varying(100),
    source_system character varying(64),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: journal_entries_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.journal_entries_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: journal_entries_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.journal_entries_id_seq OWNED BY public.journal_entries.id;


--
-- Name: journal_line_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.journal_line_items (
    id bigint NOT NULL,
    journal_entry_id bigint NOT NULL,
    account_id bigint NOT NULL,
    debit numeric(18,2) DEFAULT '0'::numeric NOT NULL,
    credit numeric(18,2) DEFAULT '0'::numeric NOT NULL
);


--
-- Name: journal_line_items_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.journal_line_items_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: journal_line_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.journal_line_items_id_seq OWNED BY public.journal_line_items.id;


--
-- Name: knowledge_base_entries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.knowledge_base_entries (
    id uuid NOT NULL,
    category character varying(100) NOT NULL,
    question text,
    answer text NOT NULL,
    keywords character varying[],
    property_id uuid,
    qdrant_point_id uuid,
    usage_count integer,
    helpful_count integer,
    not_helpful_count integer,
    last_used_at timestamp without time zone,
    is_active boolean,
    source character varying(100),
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


--
-- Name: leads; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.leads (
    id uuid NOT NULL,
    streamline_lead_id character varying(100),
    guest_name character varying(255),
    email character varying(255),
    phone character varying(20),
    guest_message text,
    status character varying(20) NOT NULL,
    ai_score integer,
    source character varying(50),
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


--
-- Name: learned_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.learned_rules (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    property_id uuid,
    rule_name character varying(255) NOT NULL,
    trigger_condition jsonb NOT NULL,
    adjustment_type character varying(20) NOT NULL,
    adjustment_value double precision NOT NULL,
    confidence_score double precision DEFAULT 0.0 NOT NULL,
    status character varying(30) DEFAULT 'pending_approval'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: legacy_pages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.legacy_pages (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    slug character varying(255) NOT NULL,
    title character varying(500) NOT NULL,
    body_value text,
    body_summary text,
    body_format character varying(50) DEFAULT 'full_html'::character varying,
    entity_type character varying(50) DEFAULT 'node'::character varying,
    bundle character varying(100) DEFAULT 'page'::character varying,
    language character varying(10) DEFAULT 'en'::character varying,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: legal_case_statements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.legal_case_statements (
    id character varying NOT NULL,
    case_slug character varying NOT NULL,
    entity_name character varying NOT NULL,
    quote_text character varying NOT NULL,
    source_ref character varying NOT NULL,
    stated_at timestamp without time zone,
    created_at timestamp without time zone
);


--
-- Name: legal_hive_mind_feedback_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.legal_hive_mind_feedback_events (
    id character varying NOT NULL,
    case_slug character varying NOT NULL,
    module_type character varying NOT NULL,
    original_swarm_text character varying NOT NULL,
    human_edited_text character varying NOT NULL,
    accepted boolean,
    user_id character varying,
    created_at timestamp without time zone
);


--
-- Name: llm_training_captures; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.llm_training_captures (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    source_module character varying(120) NOT NULL,
    model_used character varying(120) NOT NULL,
    user_prompt text NOT NULL,
    assistant_resp text NOT NULL,
    quality_score double precision,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    eval_holdout boolean DEFAULT false NOT NULL,
    served_by_endpoint character varying(256),
    served_vector_store character varying(64),
    escalated_from character varying(256),
    sovereign_attempt text,
    teacher_endpoint character varying(256),
    teacher_model character varying(128),
    task_type character varying(64),
    judge_decision character varying(16),
    judge_reasoning text,
    capture_metadata jsonb
);


--
-- Name: management_splits; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.management_splits (
    id bigint NOT NULL,
    property_id character varying(100) NOT NULL,
    owner_pct numeric(6,2) NOT NULL,
    pm_pct numeric(6,2) NOT NULL,
    effective_date date NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: management_splits_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.management_splits_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: management_splits_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.management_splits_id_seq OWNED BY public.management_splits.id;


--
-- Name: marketing_articles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.marketing_articles (
    id uuid NOT NULL,
    title character varying(255) NOT NULL,
    slug character varying(255) NOT NULL,
    content_body_html text NOT NULL,
    author character varying(255),
    published_date timestamp with time zone,
    category_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: marketing_attribution; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.marketing_attribution (
    id bigint NOT NULL,
    property_id character varying(100) NOT NULL,
    period_start date NOT NULL,
    period_end date NOT NULL,
    ad_spend numeric(12,2) DEFAULT 0 NOT NULL,
    impressions integer DEFAULT 0 NOT NULL,
    clicks integer DEFAULT 0 NOT NULL,
    direct_bookings integer DEFAULT 0 NOT NULL,
    gross_revenue numeric(12,2) DEFAULT 0 NOT NULL,
    roas numeric(12,2) DEFAULT 0 NOT NULL,
    campaign_notes text,
    entered_by character varying(100),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: marketing_attribution_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.marketing_attribution_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: marketing_attribution_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.marketing_attribution_id_seq OWNED BY public.marketing_attribution.id;


--
-- Name: message_queue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.message_queue (
    id uuid NOT NULL,
    quote_id uuid NOT NULL,
    template_id uuid NOT NULL,
    status character varying(20) NOT NULL,
    rendered_subject character varying(1000) NOT NULL,
    rendered_body text NOT NULL,
    created_at timestamp without time zone
);


--
-- Name: message_templates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.message_templates (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    category character varying(50) NOT NULL,
    subject character varying(255),
    body text NOT NULL,
    variables character varying[],
    trigger_type character varying(50),
    trigger_offset_days integer,
    trigger_time time without time zone,
    is_active boolean,
    send_priority integer,
    language character varying(10),
    usage_count integer,
    last_used_at timestamp without time zone,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


--
-- Name: messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.messages (
    id uuid NOT NULL,
    external_id character varying(255),
    guest_id uuid,
    reservation_id uuid,
    direction character varying(20) NOT NULL,
    phone_from character varying(20) NOT NULL,
    phone_to character varying(20) NOT NULL,
    body text NOT NULL,
    intent character varying(50),
    sentiment character varying(20),
    category character varying(50),
    status character varying(50) NOT NULL,
    is_auto_response boolean,
    ai_confidence numeric(4,3),
    requires_human_review boolean,
    human_reviewed_at timestamp without time zone,
    human_reviewed_by character varying(100),
    sent_at timestamp without time zone,
    delivered_at timestamp without time zone,
    read_at timestamp without time zone,
    error_code character varying(50),
    error_message text,
    provider character varying(50),
    cost_amount numeric(8,4),
    num_segments integer,
    trace_id uuid,
    metadata jsonb,
    created_at timestamp without time zone
);


--
-- Name: openshell_audit_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.openshell_audit_logs (
    id uuid NOT NULL,
    actor_id character varying(255),
    actor_email character varying(255),
    action character varying(120) NOT NULL,
    resource_type character varying(120) NOT NULL,
    resource_id character varying(255),
    purpose character varying(255),
    tool_name character varying(120),
    redaction_status character varying(50) NOT NULL,
    model_route character varying(120),
    outcome character varying(50) NOT NULL,
    request_id character varying(100),
    metadata_json jsonb NOT NULL,
    payload_hash character varying(128) NOT NULL,
    prev_hash character varying(128),
    entry_hash character varying(128) NOT NULL,
    signature text NOT NULL,
    created_at timestamp without time zone NOT NULL
);


--
-- Name: operator_overrides; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.operator_overrides (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    escalation_id uuid NOT NULL,
    operator_email character varying(255) NOT NULL,
    override_action character varying(7) NOT NULL,
    final_payload jsonb NOT NULL,
    "timestamp" timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT operator_override_action CHECK (((override_action)::text = ANY (ARRAY[('approve'::character varying)::text, ('reject'::character varying)::text, ('modify'::character varying)::text])))
);


--
-- Name: ota_micro_updates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ota_micro_updates (
    id uuid NOT NULL,
    property_id uuid,
    channel character varying(80) NOT NULL,
    patch_payload jsonb NOT NULL,
    status character varying(30) NOT NULL,
    error text,
    created_at timestamp without time zone NOT NULL
);


--
-- Name: owner_balance_periods; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.owner_balance_periods (
    id bigint NOT NULL,
    owner_payout_account_id bigint NOT NULL,
    period_start date NOT NULL,
    period_end date NOT NULL,
    opening_balance numeric(12,2) NOT NULL,
    closing_balance numeric(12,2) NOT NULL,
    total_revenue numeric(12,2) DEFAULT 0 NOT NULL,
    total_commission numeric(12,2) DEFAULT 0 NOT NULL,
    total_charges numeric(12,2) DEFAULT 0 NOT NULL,
    total_payments numeric(12,2) DEFAULT 0 NOT NULL,
    total_owner_income numeric(12,2) DEFAULT 0 NOT NULL,
    status public.statement_period_status DEFAULT 'draft'::public.statement_period_status NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    approved_at timestamp with time zone,
    approved_by character varying(255),
    paid_at timestamp with time zone,
    emailed_at timestamp with time zone,
    notes text,
    voided_at timestamp with time zone,
    voided_by character varying(255),
    paid_by character varying(255),
    stripe_transfer_id character varying(100),
    paid_amount numeric(12,2),
    CONSTRAINT chk_obp_ledger_equation CHECK ((closing_balance = (((((opening_balance + total_revenue) - total_commission) - total_charges) - total_payments) + total_owner_income))),
    CONSTRAINT chk_obp_period_order CHECK ((period_end > period_start))
);


--
-- Name: owner_balance_periods_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.owner_balance_periods_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: owner_balance_periods_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.owner_balance_periods_id_seq OWNED BY public.owner_balance_periods.id;


--
-- Name: owner_charges; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.owner_charges (
    id bigint NOT NULL,
    owner_payout_account_id bigint NOT NULL,
    posting_date date NOT NULL,
    transaction_type public.owner_charge_type_enum NOT NULL,
    description character varying(500) NOT NULL,
    amount numeric(12,2) NOT NULL,
    reference_id character varying(100),
    originating_work_order_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by character varying(255) NOT NULL,
    voided_at timestamp with time zone,
    voided_by character varying(255),
    void_reason text,
    vendor_id uuid,
    markup_percentage numeric(5,2) DEFAULT 0.00 NOT NULL,
    vendor_amount numeric(12,2),
    CONSTRAINT chk_oc_amount_not_zero CHECK ((amount <> (0)::numeric)),
    CONSTRAINT chk_oc_description_not_empty CHECK (((description)::text <> ''::text)),
    CONSTRAINT chk_oc_void_pair CHECK ((((voided_at IS NULL) AND (voided_by IS NULL)) OR ((voided_at IS NOT NULL) AND (voided_by IS NOT NULL))))
);


--
-- Name: owner_charges_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.owner_charges_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: owner_charges_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.owner_charges_id_seq OWNED BY public.owner_charges.id;


--
-- Name: owner_magic_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.owner_magic_tokens (
    id bigint NOT NULL,
    token_hash character varying(128) NOT NULL,
    owner_email character varying(255) NOT NULL,
    sl_owner_id character varying(50) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    used_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    commission_rate numeric(5,4),
    mailing_address_line1 character varying(255),
    mailing_address_line2 character varying(255),
    mailing_address_city character varying(100),
    mailing_address_state character varying(50),
    mailing_address_postal_code character varying(20),
    mailing_address_country character varying(50) DEFAULT 'USA'::character varying,
    CONSTRAINT chk_omt_commission_rate CHECK (((commission_rate >= (0)::numeric) AND (commission_rate <= 0.5000)))
);


--
-- Name: owner_magic_tokens_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.owner_magic_tokens_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: owner_magic_tokens_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.owner_magic_tokens_id_seq OWNED BY public.owner_magic_tokens.id;


--
-- Name: owner_marketing_preferences; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.owner_marketing_preferences (
    id bigint NOT NULL,
    property_id character varying(100) NOT NULL,
    marketing_pct numeric(6,2) DEFAULT 0 NOT NULL,
    enabled boolean DEFAULT false NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_by character varying(100)
);


--
-- Name: owner_marketing_preferences_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.owner_marketing_preferences_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: owner_marketing_preferences_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.owner_marketing_preferences_id_seq OWNED BY public.owner_marketing_preferences.id;


--
-- Name: owner_markup_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.owner_markup_rules (
    id bigint NOT NULL,
    property_id character varying(100) NOT NULL,
    expense_category character varying(64) DEFAULT 'ALL'::character varying NOT NULL,
    markup_percentage numeric(6,2) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: owner_markup_rules_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.owner_markup_rules_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: owner_markup_rules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.owner_markup_rules_id_seq OWNED BY public.owner_markup_rules.id;


--
-- Name: owner_payout_accounts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.owner_payout_accounts (
    id bigint NOT NULL,
    property_id character varying(100) NOT NULL,
    owner_name character varying(255) NOT NULL,
    owner_email character varying(255),
    stripe_account_id character varying(255),
    account_status character varying(64) DEFAULT 'onboarding'::character varying NOT NULL,
    instant_payout boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    payout_schedule character varying(20) DEFAULT 'manual'::character varying NOT NULL,
    payout_day_of_week integer,
    payout_day_of_month integer,
    last_payout_at timestamp with time zone,
    next_scheduled_payout timestamp with time zone,
    minimum_payout_threshold numeric(10,2) DEFAULT 100.00 NOT NULL,
    commission_rate numeric(5,4) NOT NULL,
    streamline_owner_id integer,
    mailing_address_line1 character varying(255),
    mailing_address_line2 character varying(255),
    mailing_address_city character varying(100),
    mailing_address_state character varying(50),
    mailing_address_postal_code character varying(20),
    mailing_address_country character varying(50) DEFAULT 'USA'::character varying,
    owner_middle_name character varying(100),
    CONSTRAINT chk_opa_commission_rate CHECK (((commission_rate >= (0)::numeric) AND (commission_rate <= 0.5000)))
);


--
-- Name: owner_payout_accounts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.owner_payout_accounts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: owner_payout_accounts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.owner_payout_accounts_id_seq OWNED BY public.owner_payout_accounts.id;


--
-- Name: owner_property_map; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.owner_property_map (
    id bigint NOT NULL,
    sl_owner_id character varying(50) NOT NULL,
    unit_id character varying(100) NOT NULL,
    owner_name character varying(255) NOT NULL,
    email character varying(255),
    phone character varying(40),
    property_name character varying(255),
    live_balance numeric(12,2) DEFAULT 0 NOT NULL,
    synced_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: owner_property_map_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.owner_property_map_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: owner_property_map_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.owner_property_map_id_seq OWNED BY public.owner_property_map.id;


--
-- Name: owner_statement_sends; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.owner_statement_sends (
    id bigint NOT NULL,
    owner_payout_account_id bigint NOT NULL,
    property_id uuid NOT NULL,
    statement_period_start date NOT NULL,
    statement_period_end date NOT NULL,
    sent_at timestamp with time zone,
    sent_to_email character varying(255),
    crog_total_amount numeric(12,2),
    streamline_total_amount numeric(12,2),
    source_used character varying(20),
    comparison_status character varying(30),
    comparison_diff_cents integer,
    email_message_id character varying(255),
    error_message text,
    is_test boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT owner_statement_sends_comparison_status_check CHECK (((comparison_status)::text = ANY (ARRAY[('match'::character varying)::text, ('mismatch'::character varying)::text, ('streamline_unavailable'::character varying)::text, ('not_compared'::character varying)::text]))),
    CONSTRAINT owner_statement_sends_source_used_check CHECK (((source_used)::text = ANY (ARRAY[('crog'::character varying)::text, ('streamline'::character varying)::text, ('failed'::character varying)::text])))
);


--
-- Name: owner_statement_sends_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.owner_statement_sends_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: owner_statement_sends_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.owner_statement_sends_id_seq OWNED BY public.owner_statement_sends.id;


--
-- Name: parity_audits; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.parity_audits (
    id uuid NOT NULL,
    reservation_id uuid NOT NULL,
    confirmation_id character varying(100) NOT NULL,
    local_total numeric(12,2) NOT NULL,
    streamline_total numeric(12,2) NOT NULL,
    delta numeric(12,2) NOT NULL,
    local_breakdown jsonb DEFAULT '{}'::jsonb NOT NULL,
    streamline_breakdown jsonb DEFAULT '{}'::jsonb NOT NULL,
    status character varying(30) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: payout_ledger; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.payout_ledger (
    id bigint NOT NULL,
    property_id character varying(100) NOT NULL,
    confirmation_code character varying(100),
    gross_amount numeric(12,2) DEFAULT 0 NOT NULL,
    owner_amount numeric(12,2) DEFAULT 0 NOT NULL,
    stripe_transfer_id character varying(255),
    stripe_payout_id character varying(255),
    status character varying(64) DEFAULT 'staged'::character varying NOT NULL,
    initiated_at timestamp with time zone,
    completed_at timestamp with time zone,
    failure_reason text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: payout_ledger_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.payout_ledger_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: payout_ledger_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.payout_ledger_id_seq OWNED BY public.payout_ledger.id;


--
-- Name: pending_sync; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pending_sync (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    reservation_id uuid NOT NULL,
    property_id uuid NOT NULL,
    sync_type character varying(50) DEFAULT 'create_reservation'::character varying NOT NULL,
    status character varying(30) DEFAULT 'pending'::character varying NOT NULL,
    attempt_count integer DEFAULT 0 NOT NULL,
    last_error text,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    resolved_at timestamp with time zone
);


--
-- Name: pricing_overrides; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pricing_overrides (
    id uuid NOT NULL,
    property_id uuid NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    adjustment_percentage numeric(6,2) NOT NULL,
    reason character varying(500) NOT NULL,
    approved_by character varying(255) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_pricing_overrides_adjustment_range CHECK (((adjustment_percentage >= '-100.00'::numeric) AND (adjustment_percentage <= 100.00))),
    CONSTRAINT ck_pricing_overrides_date_order CHECK ((end_date >= start_date))
);


--
-- Name: properties; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.properties (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    slug character varying(255) NOT NULL,
    property_type character varying(50) NOT NULL,
    bedrooms integer NOT NULL,
    bathrooms numeric(3,1) NOT NULL,
    max_guests integer NOT NULL,
    address text,
    latitude numeric(10,8),
    longitude numeric(11,8),
    wifi_ssid character varying(255),
    wifi_password character varying(255),
    access_code_type character varying(50),
    access_code_location text,
    parking_instructions text,
    rate_card jsonb,
    availability jsonb,
    default_housekeeper_id uuid,
    default_clean_minutes integer,
    streamline_checklist_id character varying(100),
    amenities jsonb,
    qdrant_point_id uuid,
    streamline_property_id character varying(100),
    ota_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    owner_id character varying(100),
    owner_name character varying(255),
    owner_balance jsonb,
    is_active boolean,
    created_at timestamp without time zone,
    updated_at timestamp without time zone,
    rates_notes text,
    video_urls jsonb,
    county character varying(100),
    city_limits boolean DEFAULT false NOT NULL,
    cleaning_fee numeric(10,2),
    renting_state public.property_renting_state DEFAULT 'active'::public.property_renting_state NOT NULL,
    property_group character varying(100),
    city character varying(100),
    state character varying(50),
    postal_code character varying(20)
);


--
-- Name: property_fees; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.property_fees (
    id uuid NOT NULL,
    property_id uuid NOT NULL,
    fee_id uuid NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: property_images; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.property_images (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    property_id uuid NOT NULL,
    legacy_url character varying(2048) NOT NULL,
    sovereign_url character varying(2048),
    display_order integer DEFAULT 0 NOT NULL,
    alt_text character varying(512) DEFAULT ''::character varying NOT NULL,
    is_hero boolean DEFAULT false NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    CONSTRAINT ck_property_images_status CHECK (((status)::text = ANY (ARRAY[('pending'::character varying)::text, ('ingested'::character varying)::text, ('failed'::character varying)::text])))
);


--
-- Name: property_knowledge; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.property_knowledge (
    id uuid NOT NULL,
    property_id uuid,
    category character varying(80) NOT NULL,
    content text NOT NULL,
    source character varying(120) NOT NULL,
    tags jsonb NOT NULL,
    confidence character varying(20) NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


--
-- Name: property_knowledge_chunks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.property_knowledge_chunks (
    id uuid NOT NULL,
    property_id uuid NOT NULL,
    content text NOT NULL,
    embedding text NOT NULL,
    created_at timestamp without time zone NOT NULL
);


--
-- Name: property_stay_restrictions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.property_stay_restrictions (
    id uuid NOT NULL,
    property_id uuid NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    is_blackout boolean NOT NULL,
    must_check_in_on_day smallint,
    must_check_out_on_day smallint,
    source character varying(32) NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


--
-- Name: property_taxes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.property_taxes (
    id uuid NOT NULL,
    property_id uuid NOT NULL,
    tax_id uuid NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: property_utilities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.property_utilities (
    id uuid NOT NULL,
    property_id uuid NOT NULL,
    service_type character varying(50) NOT NULL,
    provider_name character varying(255) NOT NULL,
    account_number character varying(255),
    account_holder character varying(255),
    portal_url text,
    portal_username text,
    portal_password_enc text,
    contact_phone character varying(50),
    contact_email character varying(255),
    notes text,
    monthly_budget numeric(10,2),
    is_active boolean,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


--
-- Name: quote_options; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quote_options (
    id uuid NOT NULL,
    quote_id uuid NOT NULL,
    property_id uuid NOT NULL,
    check_in_date date NOT NULL,
    check_out_date date NOT NULL,
    base_rent numeric(12,2),
    taxes numeric(12,2),
    fees numeric(12,2),
    total_price numeric(12,2),
    booking_link character varying(500),
    created_at timestamp without time zone
);


--
-- Name: quotes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quotes (
    id uuid NOT NULL,
    lead_id uuid NOT NULL,
    status character varying(20) NOT NULL,
    payment_method character varying(20),
    expires_at timestamp without time zone,
    ai_drafted_email_body text,
    ai_draft_model character varying(100),
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


--
-- Name: recovery_parity_comparisons; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.recovery_parity_comparisons (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    dedupe_hash character varying(64) NOT NULL,
    session_fp character varying(128) NOT NULL,
    guest_id uuid,
    property_slug character varying(255),
    drop_off_point character varying(64) NOT NULL,
    intent_score_estimate double precision NOT NULL,
    legacy_template_key character varying(80) NOT NULL,
    legacy_body text NOT NULL,
    sovereign_body text NOT NULL,
    parity_summary jsonb NOT NULL,
    candidate_snapshot jsonb NOT NULL,
    async_job_run_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: rental_agreements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rental_agreements (
    id uuid NOT NULL,
    guest_id uuid NOT NULL,
    reservation_id uuid,
    property_id uuid,
    template_id uuid,
    agreement_type character varying(50) NOT NULL,
    rendered_content text NOT NULL,
    status character varying(30) NOT NULL,
    sent_at timestamp without time zone,
    sent_via character varying(20),
    agreement_url text,
    expires_at timestamp without time zone,
    first_viewed_at timestamp without time zone,
    view_count integer,
    signed_at timestamp without time zone,
    signature_type character varying(30),
    signature_data text,
    signer_name character varying(200),
    signer_email character varying(255),
    initials_data text,
    initials_pages jsonb,
    signer_ip_address character varying(45),
    signer_user_agent text,
    signer_device_fingerprint character varying(255),
    consent_recorded boolean,
    pdf_url text,
    pdf_generated_at timestamp without time zone,
    reminder_count integer,
    last_reminder_at timestamp without time zone,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


--
-- Name: reservation_holds; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reservation_holds (
    id uuid NOT NULL,
    property_id uuid NOT NULL,
    guest_id uuid,
    converted_reservation_id uuid,
    session_id character varying(255) NOT NULL,
    check_in_date date NOT NULL,
    check_out_date date NOT NULL,
    num_guests integer NOT NULL,
    status character varying(50) NOT NULL,
    amount_total numeric(12,2),
    quote_snapshot jsonb,
    payment_intent_id character varying(255),
    special_requests text,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_reservation_holds_date_order CHECK ((check_out_date > check_in_date)),
    CONSTRAINT ck_reservation_holds_status CHECK (((status)::text = ANY (ARRAY[('active'::character varying)::text, ('expired'::character varying)::text, ('converted'::character varying)::text])))
);


--
-- Name: reservations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reservations (
    id uuid NOT NULL,
    confirmation_code character varying(50) NOT NULL,
    guest_id uuid NOT NULL,
    property_id uuid NOT NULL,
    guest_email character varying(255) DEFAULT ''::character varying NOT NULL,
    guest_name character varying(255) DEFAULT ''::character varying NOT NULL,
    guest_phone character varying(50),
    check_in_date date NOT NULL,
    check_out_date date NOT NULL,
    num_guests integer NOT NULL,
    num_adults integer,
    num_children integer,
    num_pets integer,
    special_requests text,
    status character varying(50) NOT NULL,
    access_code character varying(20),
    access_code_valid_from timestamp with time zone,
    access_code_valid_until timestamp with time zone,
    booking_source character varying(100),
    total_amount numeric(10,2),
    paid_amount numeric(10,2),
    balance_due numeric(10,2),
    nightly_rate numeric(10,2),
    cleaning_fee numeric(10,2),
    pet_fee numeric(10,2),
    damage_waiver_fee numeric(10,2),
    service_fee numeric(10,2),
    tax_amount numeric(10,2),
    nights_count integer,
    price_breakdown jsonb,
    currency character varying(3),
    digital_guide_sent boolean,
    pre_arrival_sent boolean,
    access_info_sent boolean,
    mid_stay_checkin_sent boolean,
    checkout_reminder_sent boolean,
    post_stay_followup_sent boolean,
    guest_rating integer,
    guest_feedback text,
    internal_notes text,
    streamline_notes jsonb,
    streamline_financial_detail jsonb,
    qdrant_point_id uuid,
    security_deposit_required boolean DEFAULT false NOT NULL,
    security_deposit_amount numeric(12,2) DEFAULT 500.00 NOT NULL,
    security_deposit_status character varying(20) DEFAULT 'none'::character varying NOT NULL,
    security_deposit_stripe_pi character varying(255),
    security_deposit_updated_at timestamp with time zone,
    streamline_reservation_id character varying(100),
    created_at timestamp with time zone,
    updated_at timestamp with time zone,
    tax_breakdown jsonb,
    security_deposit_payment_method_id character varying(255),
    is_owner_booking boolean DEFAULT false NOT NULL
);


--
-- Name: restricted_captures; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.restricted_captures (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    prompt text NOT NULL,
    response text NOT NULL,
    source_persona character varying(128),
    source_module character varying(128),
    restriction_reason character varying(256) NOT NULL,
    matched_patterns character varying[] DEFAULT '{}'::character varying[] NOT NULL,
    capture_metadata jsonb,
    eval_holdout boolean DEFAULT false NOT NULL,
    served_by_endpoint character varying(256),
    served_vector_store character varying(64),
    escalated_from character varying(256),
    sovereign_attempt text,
    teacher_endpoint character varying(256),
    teacher_model character varying(128),
    task_type character varying(64),
    judge_decision character varying(16),
    judge_reasoning text
);


--
-- Name: rue_bar_rue_legacy_recovery_templates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rue_bar_rue_legacy_recovery_templates (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    template_key character varying(80) NOT NULL,
    channel character varying(16) NOT NULL,
    audience_rule character varying(64) DEFAULT '*'::character varying NOT NULL,
    body_template text NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    source_system character varying(64) DEFAULT 'rue_ba_rue'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: scheduled_messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scheduled_messages (
    id uuid NOT NULL,
    guest_id uuid NOT NULL,
    reservation_id uuid,
    template_id uuid,
    scheduled_for timestamp without time zone NOT NULL,
    sent_at timestamp without time zone,
    phone_to character varying(20) NOT NULL,
    body text NOT NULL,
    status character varying(50) NOT NULL,
    message_id uuid,
    error_message text,
    created_at timestamp without time zone
);


--
-- Name: seo_patch_queue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.seo_patch_queue (
    id uuid NOT NULL,
    target_type character varying(32) NOT NULL,
    target_slug character varying(255) NOT NULL,
    property_id uuid,
    status character varying(30) NOT NULL,
    target_keyword character varying(255),
    campaign character varying(100) NOT NULL,
    rubric_version character varying(50),
    source_hash character varying(128) NOT NULL,
    proposed_title character varying(255) NOT NULL,
    proposed_meta_description text NOT NULL,
    proposed_h1 character varying(255) NOT NULL,
    proposed_intro text NOT NULL,
    proposed_faq jsonb NOT NULL,
    proposed_json_ld jsonb NOT NULL,
    fact_snapshot jsonb NOT NULL,
    score_overall double precision,
    score_breakdown jsonb NOT NULL,
    proposed_by character varying(100) NOT NULL,
    proposal_run_id character varying(100),
    reviewed_by character varying(100),
    review_note text,
    approved_payload jsonb NOT NULL,
    approved_at timestamp without time zone,
    deployed_at timestamp without time zone,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    CONSTRAINT ck_seo_patch_queue_status CHECK (((status)::text = ANY (ARRAY[('proposed'::character varying)::text, ('needs_revision'::character varying)::text, ('approved'::character varying)::text, ('rejected'::character varying)::text, ('deployed'::character varying)::text, ('superseded'::character varying)::text]))),
    CONSTRAINT ck_seo_patch_queue_target_type CHECK (((target_type)::text = ANY (ARRAY[('property'::character varying)::text, ('archive_review'::character varying)::text])))
);


--
-- Name: seo_patches; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.seo_patches (
    id uuid NOT NULL,
    property_id uuid,
    rubric_id uuid,
    source_intelligence_id uuid,
    source_agent character varying(120) NOT NULL,
    page_path character varying NOT NULL,
    patch_version integer NOT NULL,
    title character varying(255),
    meta_description text,
    og_title character varying(255),
    og_description text,
    jsonld_payload jsonb,
    canonical_url character varying(2048),
    h1_suggestion character varying(255),
    alt_tags jsonb,
    godhead_score double precision,
    godhead_model character varying(255),
    godhead_feedback jsonb,
    grade_attempts integer NOT NULL,
    status character varying(50) NOT NULL,
    reviewed_by character varying(255),
    reviewed_at timestamp with time zone,
    final_payload jsonb,
    deployed_at timestamp with time zone,
    deploy_task_id uuid,
    deploy_status character varying(50),
    deploy_queued_at timestamp with time zone,
    deploy_acknowledged_at timestamp with time zone,
    deploy_attempts integer DEFAULT 0 NOT NULL,
    deploy_last_error text,
    deploy_last_http_status integer,
    swarm_model character varying(255),
    swarm_node character varying(255),
    generation_ms integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: seo_rank_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.seo_rank_snapshots (
    id uuid NOT NULL,
    property_id uuid,
    keyword character varying(255) NOT NULL,
    rank_position character varying(30) NOT NULL,
    snapshot_date date NOT NULL,
    source character varying(120) NOT NULL,
    metadata_json jsonb NOT NULL
);


--
-- Name: seo_redirect_remap_queue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.seo_redirect_remap_queue (
    id uuid NOT NULL,
    source_path character varying(1024) NOT NULL,
    current_destination_path character varying(1024),
    proposed_destination_path character varying(1024) NOT NULL,
    applied_destination_path character varying(1024),
    grounding_mode character varying(100) NOT NULL,
    status character varying(30) NOT NULL,
    campaign character varying(100) NOT NULL,
    rubric_version character varying(50) NOT NULL,
    proposal_run_id character varying(100) NOT NULL,
    proposed_by character varying(100) NOT NULL,
    extracted_entities jsonb NOT NULL,
    source_snapshot jsonb NOT NULL,
    route_candidates jsonb NOT NULL,
    rationale text NOT NULL,
    grade_score double precision,
    grade_payload jsonb NOT NULL,
    reviewed_by character varying(255),
    review_note text,
    approved_at timestamp without time zone,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    CONSTRAINT ck_seo_redirect_remap_queue_status CHECK (((status)::text = ANY (ARRAY[('proposed'::character varying)::text, ('promoted'::character varying)::text, ('rejected'::character varying)::text, ('applied'::character varying)::text, ('superseded'::character varying)::text])))
);


--
-- Name: seo_redirects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.seo_redirects (
    id uuid NOT NULL,
    source_path character varying(1024) NOT NULL,
    destination_path character varying(1024) NOT NULL,
    is_permanent boolean NOT NULL,
    reason character varying(255),
    created_by character varying(255),
    updated_by character varying(255),
    is_active boolean NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


--
-- Name: seo_rubrics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.seo_rubrics (
    id uuid NOT NULL,
    keyword_cluster text NOT NULL,
    rubric_payload jsonb NOT NULL,
    source_model character varying(255) NOT NULL,
    min_pass_score double precision NOT NULL,
    status character varying(50) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: shadow_discrepancies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.shadow_discrepancies (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    "timestamp" timestamp without time zone DEFAULT now() NOT NULL,
    property_id uuid NOT NULL,
    legacy_total_cents integer NOT NULL,
    dgx_total_cents integer NOT NULL,
    delta_cents integer NOT NULL,
    legacy_payload jsonb,
    dgx_payload jsonb,
    hermes_diagnosis text,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL
);


--
-- Name: staff_invites; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.staff_invites (
    id uuid NOT NULL,
    email character varying(255) NOT NULL,
    first_name character varying(100) NOT NULL,
    last_name character varying(100) NOT NULL,
    role character varying(50) NOT NULL,
    token character varying(128) NOT NULL,
    invited_by uuid NOT NULL,
    status character varying(20) NOT NULL,
    expires_at timestamp without time zone NOT NULL,
    accepted_at timestamp without time zone,
    created_at timestamp without time zone
);


--
-- Name: staff_users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.staff_users (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    email character varying(255) NOT NULL,
    password_hash character varying(255) NOT NULL,
    first_name character varying(100) NOT NULL,
    last_name character varying(100) NOT NULL,
    role character varying(11) DEFAULT 'super_admin'::character varying NOT NULL,
    permissions jsonb,
    is_active boolean DEFAULT true NOT NULL,
    last_login_at timestamp without time zone,
    notification_phone character varying(20),
    notification_email character varying(255),
    notify_urgent boolean DEFAULT true NOT NULL,
    notify_workorders boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT staff_role CHECK (((role)::text = ANY (ARRAY[('super_admin'::character varying)::text, ('admin'::character varying)::text, ('manager'::character varying)::text, ('reviewer'::character varying)::text, ('operator'::character varying)::text, ('staff'::character varying)::text, ('maintenance'::character varying)::text])))
);


--
-- Name: storefront_intent_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.storefront_intent_events (
    id uuid NOT NULL,
    session_fp character varying(64) NOT NULL,
    event_type character varying(64) NOT NULL,
    consent_marketing boolean DEFAULT false NOT NULL,
    property_slug character varying(255),
    meta jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: storefront_session_guest_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.storefront_session_guest_links (
    id uuid NOT NULL,
    session_fp character varying(64) NOT NULL,
    guest_id uuid NOT NULL,
    reservation_hold_id uuid,
    source character varying(32) DEFAULT 'checkout_hold'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: streamline_payload_vault; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.streamline_payload_vault (
    id uuid NOT NULL,
    reservation_id character varying(100),
    event_type character varying(100) NOT NULL,
    raw_payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: stripe_connect_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.stripe_connect_events (
    id bigint NOT NULL,
    stripe_event_id character varying(255) NOT NULL,
    event_type character varying(100) NOT NULL,
    account_id character varying(255),
    transfer_id character varying(255),
    payout_id character varying(255),
    amount numeric(12,2),
    status character varying(64),
    failure_code character varying(100),
    failure_message text,
    raw_payload jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: stripe_connect_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.stripe_connect_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: stripe_connect_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.stripe_connect_events_id_seq OWNED BY public.stripe_connect_events.id;


--
-- Name: survey_templates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.survey_templates (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    survey_type character varying(50) NOT NULL,
    questions jsonb NOT NULL,
    trigger_type character varying(50),
    trigger_offset_hours integer,
    send_method character varying(20),
    is_active boolean,
    usage_count integer,
    avg_completion_rate numeric(5,2),
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


--
-- Name: swarm_escalations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.swarm_escalations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    decision_id uuid NOT NULL,
    reason_code character varying(100) NOT NULL,
    status character varying(8) DEFAULT 'pending'::character varying NOT NULL,
    CONSTRAINT swarm_escalation_status CHECK (((status)::text = ANY (ARRAY[('pending'::character varying)::text, ('resolved'::character varying)::text])))
);


--
-- Name: taxes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.taxes (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    percentage_rate numeric(6,2) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: taxonomy_categories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.taxonomy_categories (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    slug character varying(255) NOT NULL,
    description text,
    meta_title character varying(255),
    meta_description text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: taylor_quote_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.taylor_quote_requests (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    guest_email character varying(320) NOT NULL,
    check_in date NOT NULL,
    check_out date NOT NULL,
    nights integer NOT NULL,
    adults integer DEFAULT 2 NOT NULL,
    children integer DEFAULT 0 NOT NULL,
    pets integer DEFAULT 0 NOT NULL,
    status character varying(30) DEFAULT 'pending_approval'::character varying NOT NULL,
    property_options jsonb DEFAULT '[]'::jsonb NOT NULL,
    approved_by character varying(320),
    sent_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: trust_accounts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trust_accounts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    type character varying(9) NOT NULL,
    CONSTRAINT trust_account_type CHECK (((type)::text = ANY (ARRAY[('asset'::character varying)::text, ('liability'::character varying)::text])))
);


--
-- Name: trust_balance; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trust_balance (
    id bigint NOT NULL,
    property_id character varying(100) NOT NULL,
    owner_funds numeric(12,2) DEFAULT 0 NOT NULL,
    operating_funds numeric(12,2) DEFAULT 0 NOT NULL,
    escrow_funds numeric(12,2) DEFAULT 0 NOT NULL,
    security_deps numeric(12,2) DEFAULT 0 NOT NULL,
    last_updated timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: trust_balance_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.trust_balance_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: trust_balance_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.trust_balance_id_seq OWNED BY public.trust_balance.id;


--
-- Name: trust_decisions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trust_decisions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    run_id uuid NOT NULL,
    proposed_payload jsonb NOT NULL,
    deterministic_score double precision NOT NULL,
    policy_evaluation jsonb NOT NULL,
    status character varying(13) NOT NULL,
    CONSTRAINT ck_trust_decisions_deterministic_score_nonnegative CHECK ((deterministic_score >= (0)::double precision)),
    CONSTRAINT trust_decision_status CHECK (((status)::text = ANY (ARRAY[('auto_approved'::character varying)::text, ('escalated'::character varying)::text, ('blocked'::character varying)::text])))
);


--
-- Name: trust_ledger_entries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trust_ledger_entries (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    transaction_id uuid NOT NULL,
    account_id uuid NOT NULL,
    amount_cents integer NOT NULL,
    entry_type character varying(6) NOT NULL,
    CONSTRAINT ck_trust_ledger_entries_amount_positive CHECK ((amount_cents > 0)),
    CONSTRAINT trust_ledger_entry_type CHECK (((entry_type)::text = ANY (ARRAY[('debit'::character varying)::text, ('credit'::character varying)::text])))
);


--
-- Name: trust_transactions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trust_transactions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    streamline_event_id character varying(255) NOT NULL,
    decision_id uuid,
    "timestamp" timestamp with time zone DEFAULT now() NOT NULL,
    signature character varying(64),
    previous_signature character varying(64)
);


--
-- Name: utility_readings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.utility_readings (
    id uuid NOT NULL,
    utility_id uuid NOT NULL,
    reading_date date NOT NULL,
    cost numeric(10,2) NOT NULL,
    usage_amount numeric(12,4),
    usage_unit character varying(30),
    notes text,
    created_at timestamp without time zone
);


--
-- Name: v_labeling_stats; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_labeling_stats AS
 SELECT date((created_at AT TIME ZONE 'America/New_York'::text)) AS label_date,
    task_type,
    count(*) AS total_labeled,
    count(*) FILTER (WHERE ((godhead_decision)::text = 'confident'::text)) AS confident_count,
    count(*) FILTER (WHERE ((godhead_decision)::text = 'uncertain'::text)) AS uncertain_count,
    count(*) FILTER (WHERE ((godhead_decision)::text = 'escalate'::text)) AS escalate_count,
    count(*) FILTER (WHERE ((godhead_decision)::text = 'skip'::text)) AS skip_count,
    COALESCE(sum(godhead_cost_usd), (0)::numeric) AS total_cost_usd,
    count(*) FILTER (WHERE (qc_sampled = true)) AS qc_sampled_count,
    count(*) FILTER (WHERE (qc_reviewed_at IS NOT NULL)) AS qc_reviewed_count
   FROM public.capture_labels
  GROUP BY (date((created_at AT TIME ZONE 'America/New_York'::text))), task_type;


--
-- Name: v_qc_queue; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_qc_queue AS
 SELECT id,
    created_at,
    task_type,
    capture_table,
    godhead_model,
    godhead_decision,
    godhead_reasoning,
    godhead_cost_usd,
    COALESCE(( SELECT tc.user_prompt
           FROM public.llm_training_captures tc
          WHERE (tc.id = cl.capture_id)), ( SELECT rc.prompt
           FROM public.restricted_captures rc
          WHERE (rc.id = cl.capture_id))) AS user_prompt,
    COALESCE(( SELECT tc.assistant_resp
           FROM public.llm_training_captures tc
          WHERE (tc.id = cl.capture_id)), ( SELECT rc.response
           FROM public.restricted_captures rc
          WHERE (rc.id = cl.capture_id))) AS assistant_resp,
    COALESCE(( SELECT tc.source_module
           FROM public.llm_training_captures tc
          WHERE (tc.id = cl.capture_id)), ( SELECT rc.source_module
           FROM public.restricted_captures rc
          WHERE (rc.id = cl.capture_id))) AS source_module
   FROM public.capture_labels cl
  WHERE ((qc_sampled = true) AND (qc_reviewed_at IS NULL))
  ORDER BY created_at DESC;


--
-- Name: vault_audit_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vault_audit_logs (
    id uuid NOT NULL,
    user_id character varying(255) NOT NULL,
    user_email character varying(255),
    action character varying(50) NOT NULL,
    query_text text NOT NULL,
    filters_applied jsonb NOT NULL,
    result_count integer NOT NULL,
    top_score character varying(10),
    ip_address character varying(45),
    user_agent text,
    created_at timestamp without time zone NOT NULL
);


--
-- Name: vendors; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vendors (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(200) NOT NULL,
    trade character varying(80),
    phone character varying(40),
    email character varying(255),
    insurance_expiry date,
    active boolean DEFAULT true NOT NULL,
    hourly_rate numeric(8,2),
    regions jsonb DEFAULT '[]'::jsonb NOT NULL,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: vrs_add_ons; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vrs_add_ons (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    description text NOT NULL,
    price numeric(12,2) NOT NULL,
    pricing_model character varying(9) NOT NULL,
    is_active boolean NOT NULL,
    scope character varying(17) NOT NULL,
    property_id uuid,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    CONSTRAINT ck_vrs_add_ons_price_nonnegative CHECK ((price >= (0)::numeric)),
    CONSTRAINT ck_vrs_add_ons_scope_property_consistency CHECK (((((scope)::text = 'global'::text) AND (property_id IS NULL)) OR (((scope)::text = 'property_specific'::text) AND (property_id IS NOT NULL)))),
    CONSTRAINT vrs_add_on_pricing_model CHECK (((pricing_model)::text = ANY (ARRAY[('flat_fee'::character varying)::text, ('per_night'::character varying)::text, ('per_guest'::character varying)::text]))),
    CONSTRAINT vrs_add_on_scope CHECK (((scope)::text = ANY (ARRAY[('global'::character varying)::text, ('property_specific'::character varying)::text])))
);


--
-- Name: vrs_automation_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vrs_automation_events (
    id uuid NOT NULL,
    rule_id uuid,
    entity_type character varying(50) NOT NULL,
    entity_id character varying(100) NOT NULL,
    event_type character varying(50) NOT NULL,
    previous_state jsonb DEFAULT '{}'::jsonb NOT NULL,
    current_state jsonb DEFAULT '{}'::jsonb NOT NULL,
    action_result character varying(20),
    error_detail text,
    created_at timestamp without time zone
);


--
-- Name: vrs_automations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vrs_automations (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    target_entity character varying(50) NOT NULL,
    trigger_event character varying(50) NOT NULL,
    conditions jsonb DEFAULT '{}'::jsonb NOT NULL,
    action_type character varying(50) NOT NULL,
    action_payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


--
-- Name: work_orders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.work_orders (
    id uuid NOT NULL,
    ticket_number character varying(50) NOT NULL,
    property_id uuid NOT NULL,
    reservation_id uuid,
    guest_id uuid,
    reported_via_message_id uuid,
    title character varying(255) NOT NULL,
    description text NOT NULL,
    category character varying(50) NOT NULL,
    priority character varying(20) NOT NULL,
    status character varying(50) NOT NULL,
    assigned_to character varying(255),
    assigned_at timestamp without time zone,
    resolved_at timestamp without time zone,
    resolution_notes text,
    cost_amount numeric(10,2),
    photo_urls character varying[],
    qdrant_point_id uuid,
    created_by character varying(100),
    created_at timestamp without time zone,
    updated_at timestamp without time zone,
    legacy_assigned_to character varying(255),
    assigned_vendor_id uuid
);


--
-- Name: yield_overrides; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.yield_overrides (
    id uuid NOT NULL,
    property_id uuid NOT NULL,
    reason character varying(255) NOT NULL,
    override_payload jsonb NOT NULL,
    created_by character varying(120) NOT NULL,
    created_at timestamp without time zone NOT NULL
);


--
-- Name: yield_simulations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.yield_simulations (
    id uuid NOT NULL,
    property_id uuid NOT NULL,
    assumptions jsonb NOT NULL,
    simulated_revenue numeric(12,2) NOT NULL,
    simulated_margin numeric(12,2) NOT NULL,
    created_at timestamp without time zone NOT NULL
);


--
-- Name: products; Type: TABLE; Schema: verses_schema; Owner: -
--

CREATE TABLE verses_schema.products (
    id uuid NOT NULL,
    sku character varying(50) NOT NULL,
    title character varying(255) NOT NULL,
    seo_description text,
    typography_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    image_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    stock_level integer,
    status character varying(30),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: ai_audit_ledger id; Type: DEFAULT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.ai_audit_ledger ALTER COLUMN id SET DEFAULT nextval('legal.ai_audit_ledger_id_seq'::regclass);


--
-- Name: case_statements id; Type: DEFAULT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.case_statements ALTER COLUMN id SET DEFAULT nextval('legal.case_statements_id_seq'::regclass);


--
-- Name: cases id; Type: DEFAULT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.cases ALTER COLUMN id SET DEFAULT nextval('legal.cases_id_seq'::regclass);


--
-- Name: event_log id; Type: DEFAULT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.event_log ALTER COLUMN id SET DEFAULT nextval('legal.event_log_id_seq'::regclass);


--
-- Name: mail_ingester_metrics id; Type: DEFAULT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.mail_ingester_metrics ALTER COLUMN id SET DEFAULT nextval('legal.mail_ingester_metrics_id_seq'::regclass);


--
-- Name: priority_sender_rules id; Type: DEFAULT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.priority_sender_rules ALTER COLUMN id SET DEFAULT nextval('legal.priority_sender_rules_id_seq'::regclass);


--
-- Name: vault_documents id; Type: DEFAULT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.vault_documents ALTER COLUMN id SET DEFAULT nextval('legal.vault_documents_id_seq'::regclass);


--
-- Name: accounts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts ALTER COLUMN id SET DEFAULT nextval('public.accounts_id_seq'::regclass);


--
-- Name: capex_staging id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.capex_staging ALTER COLUMN id SET DEFAULT nextval('public.capex_staging_id_seq'::regclass);


--
-- Name: deferred_api_writes id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deferred_api_writes ALTER COLUMN id SET DEFAULT nextval('public.deferred_api_writes_id_seq'::regclass);


--
-- Name: journal_entries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_entries ALTER COLUMN id SET DEFAULT nextval('public.journal_entries_id_seq'::regclass);


--
-- Name: journal_line_items id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_line_items ALTER COLUMN id SET DEFAULT nextval('public.journal_line_items_id_seq'::regclass);


--
-- Name: management_splits id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.management_splits ALTER COLUMN id SET DEFAULT nextval('public.management_splits_id_seq'::regclass);


--
-- Name: marketing_attribution id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.marketing_attribution ALTER COLUMN id SET DEFAULT nextval('public.marketing_attribution_id_seq'::regclass);


--
-- Name: owner_balance_periods id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_balance_periods ALTER COLUMN id SET DEFAULT nextval('public.owner_balance_periods_id_seq'::regclass);


--
-- Name: owner_charges id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_charges ALTER COLUMN id SET DEFAULT nextval('public.owner_charges_id_seq'::regclass);


--
-- Name: owner_magic_tokens id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_magic_tokens ALTER COLUMN id SET DEFAULT nextval('public.owner_magic_tokens_id_seq'::regclass);


--
-- Name: owner_marketing_preferences id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_marketing_preferences ALTER COLUMN id SET DEFAULT nextval('public.owner_marketing_preferences_id_seq'::regclass);


--
-- Name: owner_markup_rules id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_markup_rules ALTER COLUMN id SET DEFAULT nextval('public.owner_markup_rules_id_seq'::regclass);


--
-- Name: owner_payout_accounts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_payout_accounts ALTER COLUMN id SET DEFAULT nextval('public.owner_payout_accounts_id_seq'::regclass);


--
-- Name: owner_property_map id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_property_map ALTER COLUMN id SET DEFAULT nextval('public.owner_property_map_id_seq'::regclass);


--
-- Name: owner_statement_sends id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_statement_sends ALTER COLUMN id SET DEFAULT nextval('public.owner_statement_sends_id_seq'::regclass);


--
-- Name: payout_ledger id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payout_ledger ALTER COLUMN id SET DEFAULT nextval('public.payout_ledger_id_seq'::regclass);


--
-- Name: stripe_connect_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stripe_connect_events ALTER COLUMN id SET DEFAULT nextval('public.stripe_connect_events_id_seq'::regclass);


--
-- Name: trust_balance id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trust_balance ALTER COLUMN id SET DEFAULT nextval('public.trust_balance_id_seq'::regclass);


--
-- Name: deliberation_logs deliberation_logs_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.deliberation_logs
    ADD CONSTRAINT deliberation_logs_pkey PRIMARY KEY (id);


--
-- Name: acquisition_documents acquisition_documents_pkey; Type: CONSTRAINT; Schema: crog_acquisition; Owner: -
--

ALTER TABLE ONLY crog_acquisition.acquisition_documents
    ADD CONSTRAINT acquisition_documents_pkey PRIMARY KEY (id);


--
-- Name: acquisition_pipeline acquisition_pipeline_pkey; Type: CONSTRAINT; Schema: crog_acquisition; Owner: -
--

ALTER TABLE ONLY crog_acquisition.acquisition_pipeline
    ADD CONSTRAINT acquisition_pipeline_pkey PRIMARY KEY (id);


--
-- Name: due_diligence due_diligence_pkey; Type: CONSTRAINT; Schema: crog_acquisition; Owner: -
--

ALTER TABLE ONLY crog_acquisition.due_diligence
    ADD CONSTRAINT due_diligence_pkey PRIMARY KEY (id);


--
-- Name: intel_events intel_events_pkey; Type: CONSTRAINT; Schema: crog_acquisition; Owner: -
--

ALTER TABLE ONLY crog_acquisition.intel_events
    ADD CONSTRAINT intel_events_pkey PRIMARY KEY (id);


--
-- Name: owner_contacts owner_contacts_pkey; Type: CONSTRAINT; Schema: crog_acquisition; Owner: -
--

ALTER TABLE ONLY crog_acquisition.owner_contacts
    ADD CONSTRAINT owner_contacts_pkey PRIMARY KEY (id);


--
-- Name: owners owners_pkey; Type: CONSTRAINT; Schema: crog_acquisition; Owner: -
--

ALTER TABLE ONLY crog_acquisition.owners
    ADD CONSTRAINT owners_pkey PRIMARY KEY (id);


--
-- Name: parcels parcels_pkey; Type: CONSTRAINT; Schema: crog_acquisition; Owner: -
--

ALTER TABLE ONLY crog_acquisition.parcels
    ADD CONSTRAINT parcels_pkey PRIMARY KEY (id);


--
-- Name: properties properties_airbnb_listing_id_key; Type: CONSTRAINT; Schema: crog_acquisition; Owner: -
--

ALTER TABLE ONLY crog_acquisition.properties
    ADD CONSTRAINT properties_airbnb_listing_id_key UNIQUE (airbnb_listing_id);


--
-- Name: properties properties_blue_ridge_str_permit_key; Type: CONSTRAINT; Schema: crog_acquisition; Owner: -
--

ALTER TABLE ONLY crog_acquisition.properties
    ADD CONSTRAINT properties_blue_ridge_str_permit_key UNIQUE (blue_ridge_str_permit);


--
-- Name: properties properties_fannin_str_cert_id_key; Type: CONSTRAINT; Schema: crog_acquisition; Owner: -
--

ALTER TABLE ONLY crog_acquisition.properties
    ADD CONSTRAINT properties_fannin_str_cert_id_key UNIQUE (fannin_str_cert_id);


--
-- Name: properties properties_google_place_id_key; Type: CONSTRAINT; Schema: crog_acquisition; Owner: -
--

ALTER TABLE ONLY crog_acquisition.properties
    ADD CONSTRAINT properties_google_place_id_key UNIQUE (google_place_id);


--
-- Name: properties properties_pkey; Type: CONSTRAINT; Schema: crog_acquisition; Owner: -
--

ALTER TABLE ONLY crog_acquisition.properties
    ADD CONSTRAINT properties_pkey PRIMARY KEY (id);


--
-- Name: properties properties_vrbo_listing_id_key; Type: CONSTRAINT; Schema: crog_acquisition; Owner: -
--

ALTER TABLE ONLY crog_acquisition.properties
    ADD CONSTRAINT properties_vrbo_listing_id_key UNIQUE (vrbo_listing_id);


--
-- Name: properties properties_zillow_zpid_key; Type: CONSTRAINT; Schema: crog_acquisition; Owner: -
--

ALTER TABLE ONLY crog_acquisition.properties
    ADD CONSTRAINT properties_zillow_zpid_key UNIQUE (zillow_zpid);


--
-- Name: str_signals str_signals_pkey; Type: CONSTRAINT; Schema: crog_acquisition; Owner: -
--

ALTER TABLE ONLY crog_acquisition.str_signals
    ADD CONSTRAINT str_signals_pkey PRIMARY KEY (id);


--
-- Name: owner_contacts uq_acquisition_owner_contacts_owner_value; Type: CONSTRAINT; Schema: crog_acquisition; Owner: -
--

ALTER TABLE ONLY crog_acquisition.owner_contacts
    ADD CONSTRAINT uq_acquisition_owner_contacts_owner_value UNIQUE (owner_id, contact_value);


--
-- Name: parcels uq_acquisition_parcels_parcel_id; Type: CONSTRAINT; Schema: crog_acquisition; Owner: -
--

ALTER TABLE ONLY crog_acquisition.parcels
    ADD CONSTRAINT uq_acquisition_parcels_parcel_id UNIQUE (parcel_id);


--
-- Name: acquisition_pipeline uq_acquisition_pipeline_property_id; Type: CONSTRAINT; Schema: crog_acquisition; Owner: -
--

ALTER TABLE ONLY crog_acquisition.acquisition_pipeline
    ADD CONSTRAINT uq_acquisition_pipeline_property_id UNIQUE (property_id);


--
-- Name: due_diligence uq_dd_pipeline_item; Type: CONSTRAINT; Schema: crog_acquisition; Owner: -
--

ALTER TABLE ONLY crog_acquisition.due_diligence
    ADD CONSTRAINT uq_dd_pipeline_item UNIQUE (pipeline_id, item_key);


--
-- Name: device_events device_events_pkey; Type: CONSTRAINT; Schema: iot_schema; Owner: -
--

ALTER TABLE ONLY iot_schema.device_events
    ADD CONSTRAINT device_events_pkey PRIMARY KEY (id);


--
-- Name: digital_twins digital_twins_pkey; Type: CONSTRAINT; Schema: iot_schema; Owner: -
--

ALTER TABLE ONLY iot_schema.digital_twins
    ADD CONSTRAINT digital_twins_pkey PRIMARY KEY (id);


--
-- Name: ai_audit_ledger ai_audit_ledger_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.ai_audit_ledger
    ADD CONSTRAINT ai_audit_ledger_pkey PRIMARY KEY (id);


--
-- Name: case_evidence case_evidence_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.case_evidence
    ADD CONSTRAINT case_evidence_pkey PRIMARY KEY (id);


--
-- Name: case_graph_edges case_graph_edges_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.case_graph_edges
    ADD CONSTRAINT case_graph_edges_pkey PRIMARY KEY (id);


--
-- Name: case_graph_edges_v2 case_graph_edges_v2_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.case_graph_edges_v2
    ADD CONSTRAINT case_graph_edges_v2_pkey PRIMARY KEY (id);


--
-- Name: case_graph_nodes case_graph_nodes_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.case_graph_nodes
    ADD CONSTRAINT case_graph_nodes_pkey PRIMARY KEY (id);


--
-- Name: case_graph_nodes_v2 case_graph_nodes_v2_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.case_graph_nodes_v2
    ADD CONSTRAINT case_graph_nodes_v2_pkey PRIMARY KEY (id);


--
-- Name: case_statements case_statements_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.case_statements
    ADD CONSTRAINT case_statements_pkey PRIMARY KEY (id);


--
-- Name: case_statements_v2 case_statements_v2_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.case_statements_v2
    ADD CONSTRAINT case_statements_v2_pkey PRIMARY KEY (id);


--
-- Name: cases cases_case_slug_key; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.cases
    ADD CONSTRAINT cases_case_slug_key UNIQUE (case_slug);


--
-- Name: cases cases_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.cases
    ADD CONSTRAINT cases_pkey PRIMARY KEY (id);


--
-- Name: deposition_kill_sheets_v2 deposition_kill_sheets_v2_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.deposition_kill_sheets_v2
    ADD CONSTRAINT deposition_kill_sheets_v2_pkey PRIMARY KEY (id);


--
-- Name: discovery_draft_items_v2 discovery_draft_items_v2_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.discovery_draft_items_v2
    ADD CONSTRAINT discovery_draft_items_v2_pkey PRIMARY KEY (id);


--
-- Name: discovery_draft_packs_v2 discovery_draft_packs_v2_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.discovery_draft_packs_v2
    ADD CONSTRAINT discovery_draft_packs_v2_pkey PRIMARY KEY (id);


--
-- Name: distillation_memory distillation_memory_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.distillation_memory
    ADD CONSTRAINT distillation_memory_pkey PRIMARY KEY (id);


--
-- Name: entities entities_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.entities
    ADD CONSTRAINT entities_pkey PRIMARY KEY (id);


--
-- Name: event_log event_log_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.event_log
    ADD CONSTRAINT event_log_pkey PRIMARY KEY (id);


--
-- Name: legal_cases legal_cases_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.legal_cases
    ADD CONSTRAINT legal_cases_pkey PRIMARY KEY (id);


--
-- Name: legal_cases legal_cases_slug_key; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.legal_cases
    ADD CONSTRAINT legal_cases_slug_key UNIQUE (slug);


--
-- Name: legal_exemplars legal_exemplars_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.legal_exemplars
    ADD CONSTRAINT legal_exemplars_pkey PRIMARY KEY (id);


--
-- Name: mail_ingester_metrics mail_ingester_metrics_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.mail_ingester_metrics
    ADD CONSTRAINT mail_ingester_metrics_pkey PRIMARY KEY (id);


--
-- Name: mail_ingester_pause mail_ingester_pause_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.mail_ingester_pause
    ADD CONSTRAINT mail_ingester_pause_pkey PRIMARY KEY (mailbox_alias);


--
-- Name: mail_ingester_state mail_ingester_state_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.mail_ingester_state
    ADD CONSTRAINT mail_ingester_state_pkey PRIMARY KEY (mailbox_alias);


--
-- Name: priority_sender_rules priority_sender_rules_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.priority_sender_rules
    ADD CONSTRAINT priority_sender_rules_pkey PRIMARY KEY (id);


--
-- Name: sanctions_alerts_v2 sanctions_alerts_v2_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.sanctions_alerts_v2
    ADD CONSTRAINT sanctions_alerts_v2_pkey PRIMARY KEY (id);


--
-- Name: sanctions_tripwire_runs_v2 sanctions_tripwire_runs_v2_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.sanctions_tripwire_runs_v2
    ADD CONSTRAINT sanctions_tripwire_runs_v2_pkey PRIMARY KEY (id);


--
-- Name: timeline_events timeline_events_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.timeline_events
    ADD CONSTRAINT timeline_events_pkey PRIMARY KEY (id);


--
-- Name: vault_documents vault_documents_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.vault_documents
    ADD CONSTRAINT vault_documents_pkey PRIMARY KEY (id);


--
-- Name: accounts accounts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT accounts_pkey PRIMARY KEY (id);


--
-- Name: activities activities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activities
    ADD CONSTRAINT activities_pkey PRIMARY KEY (id);


--
-- Name: agent_queue agent_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_queue
    ADD CONSTRAINT agent_queue_pkey PRIMARY KEY (id);


--
-- Name: agent_registry agent_registry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_registry
    ADD CONSTRAINT agent_registry_pkey PRIMARY KEY (id);


--
-- Name: agent_response_queue agent_response_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_response_queue
    ADD CONSTRAINT agent_response_queue_pkey PRIMARY KEY (id);


--
-- Name: agent_runs agent_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT agent_runs_pkey PRIMARY KEY (id);


--
-- Name: agreement_templates agreement_templates_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agreement_templates
    ADD CONSTRAINT agreement_templates_name_key UNIQUE (name);


--
-- Name: agreement_templates agreement_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agreement_templates
    ADD CONSTRAINT agreement_templates_pkey PRIMARY KEY (id);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: analytics_events analytics_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.analytics_events
    ADD CONSTRAINT analytics_events_pkey PRIMARY KEY (id);


--
-- Name: async_job_runs async_job_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.async_job_runs
    ADD CONSTRAINT async_job_runs_pkey PRIMARY KEY (id);


--
-- Name: blocked_days blocked_days_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.blocked_days
    ADD CONSTRAINT blocked_days_pkey PRIMARY KEY (id);


--
-- Name: blogs blogs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.blogs
    ADD CONSTRAINT blogs_pkey PRIMARY KEY (id);


--
-- Name: capex_staging capex_staging_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.capex_staging
    ADD CONSTRAINT capex_staging_pkey PRIMARY KEY (id);


--
-- Name: capture_labels capture_labels_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.capture_labels
    ADD CONSTRAINT capture_labels_pkey PRIMARY KEY (id);


--
-- Name: channel_mappings channel_mappings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channel_mappings
    ADD CONSTRAINT channel_mappings_pkey PRIMARY KEY (id);


--
-- Name: citation_records citation_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.citation_records
    ADD CONSTRAINT citation_records_pkey PRIMARY KEY (id);


--
-- Name: cleaners cleaners_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cleaners
    ADD CONSTRAINT cleaners_pkey PRIMARY KEY (id);


--
-- Name: competitor_listings competitor_listings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.competitor_listings
    ADD CONSTRAINT competitor_listings_pkey PRIMARY KEY (id);


--
-- Name: concierge_queue concierge_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.concierge_queue
    ADD CONSTRAINT concierge_queue_pkey PRIMARY KEY (id);


--
-- Name: concierge_recovery_dispatches concierge_recovery_dispatches_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.concierge_recovery_dispatches
    ADD CONSTRAINT concierge_recovery_dispatches_pkey PRIMARY KEY (id);


--
-- Name: damage_claims damage_claims_claim_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.damage_claims
    ADD CONSTRAINT damage_claims_claim_number_key UNIQUE (claim_number);


--
-- Name: damage_claims damage_claims_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.damage_claims
    ADD CONSTRAINT damage_claims_pkey PRIMARY KEY (id);


--
-- Name: deferred_api_writes deferred_api_writes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deferred_api_writes
    ADD CONSTRAINT deferred_api_writes_pkey PRIMARY KEY (id);


--
-- Name: distillation_queue distillation_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.distillation_queue
    ADD CONSTRAINT distillation_queue_pkey PRIMARY KEY (id);


--
-- Name: email_inquirers email_inquirers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_inquirers
    ADD CONSTRAINT email_inquirers_pkey PRIMARY KEY (id);


--
-- Name: email_messages email_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_messages
    ADD CONSTRAINT email_messages_pkey PRIMARY KEY (id);


--
-- Name: email_templates email_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_templates
    ADD CONSTRAINT email_templates_pkey PRIMARY KEY (id);


--
-- Name: extra_orders extra_orders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extra_orders
    ADD CONSTRAINT extra_orders_pkey PRIMARY KEY (id);


--
-- Name: extras extras_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extras
    ADD CONSTRAINT extras_pkey PRIMARY KEY (id);


--
-- Name: fees fees_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fees
    ADD CONSTRAINT fees_pkey PRIMARY KEY (id);


--
-- Name: financial_approvals financial_approvals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.financial_approvals
    ADD CONSTRAINT financial_approvals_pkey PRIMARY KEY (id);


--
-- Name: functional_nodes functional_nodes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.functional_nodes
    ADD CONSTRAINT functional_nodes_pkey PRIMARY KEY (id);


--
-- Name: guest_activities guest_activities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.guest_activities
    ADD CONSTRAINT guest_activities_pkey PRIMARY KEY (id);


--
-- Name: guest_quotes guest_quotes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.guest_quotes
    ADD CONSTRAINT guest_quotes_pkey PRIMARY KEY (id);


--
-- Name: guest_reviews guest_reviews_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.guest_reviews
    ADD CONSTRAINT guest_reviews_pkey PRIMARY KEY (id);


--
-- Name: guest_surveys guest_surveys_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.guest_surveys
    ADD CONSTRAINT guest_surveys_pkey PRIMARY KEY (id);


--
-- Name: guest_verifications guest_verifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.guest_verifications
    ADD CONSTRAINT guest_verifications_pkey PRIMARY KEY (id);


--
-- Name: guestbook_guides guestbook_guides_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.guestbook_guides
    ADD CONSTRAINT guestbook_guides_pkey PRIMARY KEY (id);


--
-- Name: guests guests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.guests
    ADD CONSTRAINT guests_pkey PRIMARY KEY (id);


--
-- Name: housekeeping_tasks housekeeping_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.housekeeping_tasks
    ADD CONSTRAINT housekeeping_tasks_pkey PRIMARY KEY (id);


--
-- Name: hunter_queue hunter_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hunter_queue
    ADD CONSTRAINT hunter_queue_pkey PRIMARY KEY (id);


--
-- Name: hunter_recovery_ops hunter_recovery_ops_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hunter_recovery_ops
    ADD CONSTRAINT hunter_recovery_ops_pkey PRIMARY KEY (id);


--
-- Name: hunter_runs hunter_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hunter_runs
    ADD CONSTRAINT hunter_runs_pkey PRIMARY KEY (id);


--
-- Name: intelligence_ledger intelligence_ledger_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.intelligence_ledger
    ADD CONSTRAINT intelligence_ledger_pkey PRIMARY KEY (id);


--
-- Name: journal_entries journal_entries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_entries
    ADD CONSTRAINT journal_entries_pkey PRIMARY KEY (id);


--
-- Name: journal_line_items journal_line_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_line_items
    ADD CONSTRAINT journal_line_items_pkey PRIMARY KEY (id);


--
-- Name: knowledge_base_entries knowledge_base_entries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_base_entries
    ADD CONSTRAINT knowledge_base_entries_pkey PRIMARY KEY (id);


--
-- Name: leads leads_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.leads
    ADD CONSTRAINT leads_pkey PRIMARY KEY (id);


--
-- Name: learned_rules learned_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learned_rules
    ADD CONSTRAINT learned_rules_pkey PRIMARY KEY (id);


--
-- Name: legacy_pages legacy_pages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legacy_pages
    ADD CONSTRAINT legacy_pages_pkey PRIMARY KEY (id);


--
-- Name: legal_case_statements legal_case_statements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legal_case_statements
    ADD CONSTRAINT legal_case_statements_pkey PRIMARY KEY (id);


--
-- Name: legal_hive_mind_feedback_events legal_hive_mind_feedback_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legal_hive_mind_feedback_events
    ADD CONSTRAINT legal_hive_mind_feedback_events_pkey PRIMARY KEY (id);


--
-- Name: llm_training_captures llm_training_captures_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_training_captures
    ADD CONSTRAINT llm_training_captures_pkey PRIMARY KEY (id);


--
-- Name: management_splits management_splits_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.management_splits
    ADD CONSTRAINT management_splits_pkey PRIMARY KEY (id);


--
-- Name: marketing_articles marketing_articles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.marketing_articles
    ADD CONSTRAINT marketing_articles_pkey PRIMARY KEY (id);


--
-- Name: marketing_attribution marketing_attribution_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.marketing_attribution
    ADD CONSTRAINT marketing_attribution_pkey PRIMARY KEY (id);


--
-- Name: message_queue message_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_queue
    ADD CONSTRAINT message_queue_pkey PRIMARY KEY (id);


--
-- Name: message_templates message_templates_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_templates
    ADD CONSTRAINT message_templates_name_key UNIQUE (name);


--
-- Name: message_templates message_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_templates
    ADD CONSTRAINT message_templates_pkey PRIMARY KEY (id);


--
-- Name: messages messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_pkey PRIMARY KEY (id);


--
-- Name: openshell_audit_logs openshell_audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openshell_audit_logs
    ADD CONSTRAINT openshell_audit_logs_pkey PRIMARY KEY (id);


--
-- Name: operator_overrides operator_overrides_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.operator_overrides
    ADD CONSTRAINT operator_overrides_pkey PRIMARY KEY (id);


--
-- Name: ota_micro_updates ota_micro_updates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ota_micro_updates
    ADD CONSTRAINT ota_micro_updates_pkey PRIMARY KEY (id);


--
-- Name: owner_balance_periods owner_balance_periods_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_balance_periods
    ADD CONSTRAINT owner_balance_periods_pkey PRIMARY KEY (id);


--
-- Name: owner_charges owner_charges_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_charges
    ADD CONSTRAINT owner_charges_pkey PRIMARY KEY (id);


--
-- Name: owner_magic_tokens owner_magic_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_magic_tokens
    ADD CONSTRAINT owner_magic_tokens_pkey PRIMARY KEY (id);


--
-- Name: owner_marketing_preferences owner_marketing_preferences_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_marketing_preferences
    ADD CONSTRAINT owner_marketing_preferences_pkey PRIMARY KEY (id);


--
-- Name: owner_markup_rules owner_markup_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_markup_rules
    ADD CONSTRAINT owner_markup_rules_pkey PRIMARY KEY (id);


--
-- Name: owner_payout_accounts owner_payout_accounts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_payout_accounts
    ADD CONSTRAINT owner_payout_accounts_pkey PRIMARY KEY (id);


--
-- Name: owner_property_map owner_property_map_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_property_map
    ADD CONSTRAINT owner_property_map_pkey PRIMARY KEY (id);


--
-- Name: owner_statement_sends owner_statement_sends_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_statement_sends
    ADD CONSTRAINT owner_statement_sends_pkey PRIMARY KEY (id);


--
-- Name: parity_audits parity_audits_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parity_audits
    ADD CONSTRAINT parity_audits_pkey PRIMARY KEY (id);


--
-- Name: payout_ledger payout_ledger_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payout_ledger
    ADD CONSTRAINT payout_ledger_pkey PRIMARY KEY (id);


--
-- Name: pending_sync pending_sync_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pending_sync
    ADD CONSTRAINT pending_sync_pkey PRIMARY KEY (id);


--
-- Name: pricing_overrides pricing_overrides_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pricing_overrides
    ADD CONSTRAINT pricing_overrides_pkey PRIMARY KEY (id);


--
-- Name: properties properties_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.properties
    ADD CONSTRAINT properties_name_key UNIQUE (name);


--
-- Name: properties properties_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.properties
    ADD CONSTRAINT properties_pkey PRIMARY KEY (id);


--
-- Name: property_fees property_fees_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.property_fees
    ADD CONSTRAINT property_fees_pkey PRIMARY KEY (id);


--
-- Name: property_images property_images_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.property_images
    ADD CONSTRAINT property_images_pkey PRIMARY KEY (id);


--
-- Name: property_knowledge_chunks property_knowledge_chunks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.property_knowledge_chunks
    ADD CONSTRAINT property_knowledge_chunks_pkey PRIMARY KEY (id);


--
-- Name: property_knowledge property_knowledge_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.property_knowledge
    ADD CONSTRAINT property_knowledge_pkey PRIMARY KEY (id);


--
-- Name: property_stay_restrictions property_stay_restrictions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.property_stay_restrictions
    ADD CONSTRAINT property_stay_restrictions_pkey PRIMARY KEY (id);


--
-- Name: property_taxes property_taxes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.property_taxes
    ADD CONSTRAINT property_taxes_pkey PRIMARY KEY (id);


--
-- Name: property_utilities property_utilities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.property_utilities
    ADD CONSTRAINT property_utilities_pkey PRIMARY KEY (id);


--
-- Name: quote_options quote_options_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quote_options
    ADD CONSTRAINT quote_options_pkey PRIMARY KEY (id);


--
-- Name: quotes quotes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotes
    ADD CONSTRAINT quotes_pkey PRIMARY KEY (id);


--
-- Name: recovery_parity_comparisons recovery_parity_comparisons_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recovery_parity_comparisons
    ADD CONSTRAINT recovery_parity_comparisons_pkey PRIMARY KEY (id);


--
-- Name: rental_agreements rental_agreements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rental_agreements
    ADD CONSTRAINT rental_agreements_pkey PRIMARY KEY (id);


--
-- Name: reservation_holds reservation_holds_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reservation_holds
    ADD CONSTRAINT reservation_holds_pkey PRIMARY KEY (id);


--
-- Name: reservations reservations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reservations
    ADD CONSTRAINT reservations_pkey PRIMARY KEY (id);


--
-- Name: restricted_captures restricted_captures_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.restricted_captures
    ADD CONSTRAINT restricted_captures_pkey PRIMARY KEY (id);


--
-- Name: rue_bar_rue_legacy_recovery_templates rue_bar_rue_legacy_recovery_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rue_bar_rue_legacy_recovery_templates
    ADD CONSTRAINT rue_bar_rue_legacy_recovery_templates_pkey PRIMARY KEY (id);


--
-- Name: scheduled_messages scheduled_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_messages
    ADD CONSTRAINT scheduled_messages_pkey PRIMARY KEY (id);


--
-- Name: seo_patch_queue seo_patch_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.seo_patch_queue
    ADD CONSTRAINT seo_patch_queue_pkey PRIMARY KEY (id);


--
-- Name: seo_patches seo_patches_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.seo_patches
    ADD CONSTRAINT seo_patches_pkey PRIMARY KEY (id);


--
-- Name: seo_rank_snapshots seo_rank_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.seo_rank_snapshots
    ADD CONSTRAINT seo_rank_snapshots_pkey PRIMARY KEY (id);


--
-- Name: seo_redirect_remap_queue seo_redirect_remap_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.seo_redirect_remap_queue
    ADD CONSTRAINT seo_redirect_remap_queue_pkey PRIMARY KEY (id);


--
-- Name: seo_redirects seo_redirects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.seo_redirects
    ADD CONSTRAINT seo_redirects_pkey PRIMARY KEY (id);


--
-- Name: seo_rubrics seo_rubrics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.seo_rubrics
    ADD CONSTRAINT seo_rubrics_pkey PRIMARY KEY (id);


--
-- Name: shadow_discrepancies shadow_discrepancies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shadow_discrepancies
    ADD CONSTRAINT shadow_discrepancies_pkey PRIMARY KEY (id);


--
-- Name: staff_invites staff_invites_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staff_invites
    ADD CONSTRAINT staff_invites_pkey PRIMARY KEY (id);


--
-- Name: staff_users staff_users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staff_users
    ADD CONSTRAINT staff_users_pkey PRIMARY KEY (id);


--
-- Name: storefront_intent_events storefront_intent_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.storefront_intent_events
    ADD CONSTRAINT storefront_intent_events_pkey PRIMARY KEY (id);


--
-- Name: storefront_session_guest_links storefront_session_guest_links_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.storefront_session_guest_links
    ADD CONSTRAINT storefront_session_guest_links_pkey PRIMARY KEY (id);


--
-- Name: streamline_payload_vault streamline_payload_vault_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.streamline_payload_vault
    ADD CONSTRAINT streamline_payload_vault_pkey PRIMARY KEY (id);


--
-- Name: stripe_connect_events stripe_connect_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stripe_connect_events
    ADD CONSTRAINT stripe_connect_events_pkey PRIMARY KEY (id);


--
-- Name: survey_templates survey_templates_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.survey_templates
    ADD CONSTRAINT survey_templates_name_key UNIQUE (name);


--
-- Name: survey_templates survey_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.survey_templates
    ADD CONSTRAINT survey_templates_pkey PRIMARY KEY (id);


--
-- Name: swarm_escalations swarm_escalations_decision_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.swarm_escalations
    ADD CONSTRAINT swarm_escalations_decision_id_key UNIQUE (decision_id);


--
-- Name: swarm_escalations swarm_escalations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.swarm_escalations
    ADD CONSTRAINT swarm_escalations_pkey PRIMARY KEY (id);


--
-- Name: taxes taxes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.taxes
    ADD CONSTRAINT taxes_pkey PRIMARY KEY (id);


--
-- Name: taxonomy_categories taxonomy_categories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.taxonomy_categories
    ADD CONSTRAINT taxonomy_categories_pkey PRIMARY KEY (id);


--
-- Name: taylor_quote_requests taylor_quote_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.taylor_quote_requests
    ADD CONSTRAINT taylor_quote_requests_pkey PRIMARY KEY (id);


--
-- Name: trust_accounts trust_accounts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trust_accounts
    ADD CONSTRAINT trust_accounts_pkey PRIMARY KEY (id);


--
-- Name: trust_balance trust_balance_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trust_balance
    ADD CONSTRAINT trust_balance_pkey PRIMARY KEY (id);


--
-- Name: trust_decisions trust_decisions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trust_decisions
    ADD CONSTRAINT trust_decisions_pkey PRIMARY KEY (id);


--
-- Name: trust_ledger_entries trust_ledger_entries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trust_ledger_entries
    ADD CONSTRAINT trust_ledger_entries_pkey PRIMARY KEY (id);


--
-- Name: trust_transactions trust_transactions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trust_transactions
    ADD CONSTRAINT trust_transactions_pkey PRIMARY KEY (id);


--
-- Name: accounts uq_accounts_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT uq_accounts_code UNIQUE (code);


--
-- Name: agent_registry uq_agent_registry_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_registry
    ADD CONSTRAINT uq_agent_registry_name UNIQUE (name);


--
-- Name: blocked_days uq_blocked_days_prop_dates_type; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.blocked_days
    ADD CONSTRAINT uq_blocked_days_prop_dates_type UNIQUE (property_id, start_date, end_date, block_type);


--
-- Name: capture_labels uq_capture_labels_capture; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.capture_labels
    ADD CONSTRAINT uq_capture_labels_capture UNIQUE (capture_id, capture_table);


--
-- Name: channel_mappings uq_channel_mappings_property_channel; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channel_mappings
    ADD CONSTRAINT uq_channel_mappings_property_channel UNIQUE (property_id, channel);


--
-- Name: competitor_listings uq_competitor_listings_dedupe_hash; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.competitor_listings
    ADD CONSTRAINT uq_competitor_listings_dedupe_hash UNIQUE (dedupe_hash);


--
-- Name: email_inquirers uq_email_inquirers_email; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_inquirers
    ADD CONSTRAINT uq_email_inquirers_email UNIQUE (email);


--
-- Name: hunter_queue uq_hunter_queue_session_fp; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hunter_queue
    ADD CONSTRAINT uq_hunter_queue_session_fp UNIQUE (session_fp);


--
-- Name: intelligence_ledger uq_intelligence_ledger_dedupe_hash; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.intelligence_ledger
    ADD CONSTRAINT uq_intelligence_ledger_dedupe_hash UNIQUE (dedupe_hash);


--
-- Name: management_splits uq_management_splits_property_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.management_splits
    ADD CONSTRAINT uq_management_splits_property_id UNIQUE (property_id);


--
-- Name: marketing_attribution uq_marketing_attribution_property_period; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.marketing_attribution
    ADD CONSTRAINT uq_marketing_attribution_property_period UNIQUE (property_id, period_start, period_end);


--
-- Name: message_queue uq_message_queue_quote_template; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_queue
    ADD CONSTRAINT uq_message_queue_quote_template UNIQUE (quote_id, template_id);


--
-- Name: owner_balance_periods uq_obp_owner_period; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_balance_periods
    ADD CONSTRAINT uq_obp_owner_period UNIQUE (owner_payout_account_id, period_start, period_end);


--
-- Name: owner_magic_tokens uq_owner_magic_tokens_token_hash; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_magic_tokens
    ADD CONSTRAINT uq_owner_magic_tokens_token_hash UNIQUE (token_hash);


--
-- Name: owner_marketing_preferences uq_owner_marketing_preferences_property_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_marketing_preferences
    ADD CONSTRAINT uq_owner_marketing_preferences_property_id UNIQUE (property_id);


--
-- Name: owner_markup_rules uq_owner_markup_rules_property_category; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_markup_rules
    ADD CONSTRAINT uq_owner_markup_rules_property_category UNIQUE (property_id, expense_category);


--
-- Name: owner_payout_accounts uq_owner_payout_accounts_property_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_payout_accounts
    ADD CONSTRAINT uq_owner_payout_accounts_property_id UNIQUE (property_id);


--
-- Name: owner_payout_accounts uq_owner_payout_accounts_stripe_account_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_payout_accounts
    ADD CONSTRAINT uq_owner_payout_accounts_stripe_account_id UNIQUE (stripe_account_id);


--
-- Name: owner_property_map uq_owner_property_map_owner_unit; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_property_map
    ADD CONSTRAINT uq_owner_property_map_owner_unit UNIQUE (sl_owner_id, unit_id);


--
-- Name: property_fees uq_property_fees_property_fee; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.property_fees
    ADD CONSTRAINT uq_property_fees_property_fee UNIQUE (property_id, fee_id);


--
-- Name: property_images uq_property_images_property_legacy_url; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.property_images
    ADD CONSTRAINT uq_property_images_property_legacy_url UNIQUE (property_id, legacy_url);


--
-- Name: property_taxes uq_property_taxes_property_tax; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.property_taxes
    ADD CONSTRAINT uq_property_taxes_property_tax UNIQUE (property_id, tax_id);


--
-- Name: rue_bar_rue_legacy_recovery_templates uq_rbr_legacy_recovery_template_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rue_bar_rue_legacy_recovery_templates
    ADD CONSTRAINT uq_rbr_legacy_recovery_template_key UNIQUE (template_key);


--
-- Name: utility_readings uq_reading_per_day; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.utility_readings
    ADD CONSTRAINT uq_reading_per_day UNIQUE (utility_id, reading_date);


--
-- Name: recovery_parity_comparisons uq_recovery_parity_comparisons_dedupe_hash; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recovery_parity_comparisons
    ADD CONSTRAINT uq_recovery_parity_comparisons_dedupe_hash UNIQUE (dedupe_hash);


--
-- Name: seo_patch_queue uq_seo_patch_queue_target_campaign_source; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.seo_patch_queue
    ADD CONSTRAINT uq_seo_patch_queue_target_campaign_source UNIQUE (target_type, target_slug, campaign, source_hash);


--
-- Name: seo_redirect_remap_queue uq_seo_redirect_remap_queue_source_campaign_run; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.seo_redirect_remap_queue
    ADD CONSTRAINT uq_seo_redirect_remap_queue_source_campaign_run UNIQUE (source_path, campaign, proposal_run_id);


--
-- Name: stripe_connect_events uq_stripe_connect_events_event_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stripe_connect_events
    ADD CONSTRAINT uq_stripe_connect_events_event_id UNIQUE (stripe_event_id);


--
-- Name: trust_accounts uq_trust_accounts_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trust_accounts
    ADD CONSTRAINT uq_trust_accounts_name UNIQUE (name);


--
-- Name: trust_balance uq_trust_balance_property_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trust_balance
    ADD CONSTRAINT uq_trust_balance_property_id UNIQUE (property_id);


--
-- Name: trust_transactions uq_trust_transactions_signature; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trust_transactions
    ADD CONSTRAINT uq_trust_transactions_signature UNIQUE (signature);


--
-- Name: trust_transactions uq_trust_transactions_streamline_event_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trust_transactions
    ADD CONSTRAINT uq_trust_transactions_streamline_event_id UNIQUE (streamline_event_id);


--
-- Name: utility_readings utility_readings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.utility_readings
    ADD CONSTRAINT utility_readings_pkey PRIMARY KEY (id);


--
-- Name: vault_audit_logs vault_audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_audit_logs
    ADD CONSTRAINT vault_audit_logs_pkey PRIMARY KEY (id);


--
-- Name: vendors vendors_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vendors
    ADD CONSTRAINT vendors_pkey PRIMARY KEY (id);


--
-- Name: vrs_add_ons vrs_add_ons_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vrs_add_ons
    ADD CONSTRAINT vrs_add_ons_pkey PRIMARY KEY (id);


--
-- Name: vrs_automation_events vrs_automation_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vrs_automation_events
    ADD CONSTRAINT vrs_automation_events_pkey PRIMARY KEY (id);


--
-- Name: vrs_automations vrs_automations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vrs_automations
    ADD CONSTRAINT vrs_automations_pkey PRIMARY KEY (id);


--
-- Name: work_orders work_orders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_orders
    ADD CONSTRAINT work_orders_pkey PRIMARY KEY (id);


--
-- Name: work_orders work_orders_ticket_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_orders
    ADD CONSTRAINT work_orders_ticket_number_key UNIQUE (ticket_number);


--
-- Name: yield_overrides yield_overrides_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.yield_overrides
    ADD CONSTRAINT yield_overrides_pkey PRIMARY KEY (id);


--
-- Name: yield_simulations yield_simulations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.yield_simulations
    ADD CONSTRAINT yield_simulations_pkey PRIMARY KEY (id);


--
-- Name: products products_pkey; Type: CONSTRAINT; Schema: verses_schema; Owner: -
--

ALTER TABLE ONLY verses_schema.products
    ADD CONSTRAINT products_pkey PRIMARY KEY (id);


--
-- Name: ix_core_deliberation_logs_created_at; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX ix_core_deliberation_logs_created_at ON core.deliberation_logs USING btree (created_at);


--
-- Name: ix_core_deliberation_logs_guest_id; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX ix_core_deliberation_logs_guest_id ON core.deliberation_logs USING btree (guest_id);


--
-- Name: ix_core_deliberation_logs_message_id; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX ix_core_deliberation_logs_message_id ON core.deliberation_logs USING btree (message_id);


--
-- Name: ix_core_deliberation_logs_property_id; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX ix_core_deliberation_logs_property_id ON core.deliberation_logs USING btree (property_id);


--
-- Name: ix_core_deliberation_logs_reservation_id; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX ix_core_deliberation_logs_reservation_id ON core.deliberation_logs USING btree (reservation_id);


--
-- Name: ix_core_deliberation_logs_session_id; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX ix_core_deliberation_logs_session_id ON core.deliberation_logs USING btree (session_id);


--
-- Name: ix_core_deliberation_logs_verdict_type; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX ix_core_deliberation_logs_verdict_type ON core.deliberation_logs USING btree (verdict_type);


--
-- Name: idx_acquisition_intel_event_type; Type: INDEX; Schema: crog_acquisition; Owner: -
--

CREATE INDEX idx_acquisition_intel_event_type ON crog_acquisition.intel_events USING btree (event_type);


--
-- Name: idx_acquisition_intel_property_time; Type: INDEX; Schema: crog_acquisition; Owner: -
--

CREATE INDEX idx_acquisition_intel_property_time ON crog_acquisition.intel_events USING btree (property_id, detected_at);


--
-- Name: idx_acquisition_owner_contacts_owner; Type: INDEX; Schema: crog_acquisition; Owner: -
--

CREATE INDEX idx_acquisition_owner_contacts_owner ON crog_acquisition.owner_contacts USING btree (owner_id);


--
-- Name: idx_acquisition_owners_legal_name; Type: INDEX; Schema: crog_acquisition; Owner: -
--

CREATE INDEX idx_acquisition_owners_legal_name ON crog_acquisition.owners USING btree (legal_name);


--
-- Name: idx_acquisition_parcels_assessed; Type: INDEX; Schema: crog_acquisition; Owner: -
--

CREATE INDEX idx_acquisition_parcels_assessed ON crog_acquisition.parcels USING btree (assessed_value);


--
-- Name: idx_acquisition_pipeline_next_action_date; Type: INDEX; Schema: crog_acquisition; Owner: -
--

CREATE INDEX idx_acquisition_pipeline_next_action_date ON crog_acquisition.acquisition_pipeline USING btree (next_action_date);


--
-- Name: idx_acquisition_pipeline_stage; Type: INDEX; Schema: crog_acquisition; Owner: -
--

CREATE INDEX idx_acquisition_pipeline_stage ON crog_acquisition.acquisition_pipeline USING btree (stage);


--
-- Name: idx_acquisition_properties_mgmt; Type: INDEX; Schema: crog_acquisition; Owner: -
--

CREATE INDEX idx_acquisition_properties_mgmt ON crog_acquisition.properties USING btree (management_company);


--
-- Name: idx_acquisition_properties_status; Type: INDEX; Schema: crog_acquisition; Owner: -
--

CREATE INDEX idx_acquisition_properties_status ON crog_acquisition.properties USING btree (status);


--
-- Name: idx_acquisition_str_signals_detected_at; Type: INDEX; Schema: crog_acquisition; Owner: -
--

CREATE INDEX idx_acquisition_str_signals_detected_at ON crog_acquisition.str_signals USING btree (detected_at);


--
-- Name: idx_acquisition_str_signals_property; Type: INDEX; Schema: crog_acquisition; Owner: -
--

CREATE INDEX idx_acquisition_str_signals_property ON crog_acquisition.str_signals USING btree (property_id);


--
-- Name: idx_acquisition_str_signals_source; Type: INDEX; Schema: crog_acquisition; Owner: -
--

CREATE INDEX idx_acquisition_str_signals_source ON crog_acquisition.str_signals USING btree (signal_source);


--
-- Name: ix_acq_docs_pipeline_id; Type: INDEX; Schema: crog_acquisition; Owner: -
--

CREATE INDEX ix_acq_docs_pipeline_id ON crog_acquisition.acquisition_documents USING btree (pipeline_id);


--
-- Name: ix_crog_acquisition_properties_owner_id; Type: INDEX; Schema: crog_acquisition; Owner: -
--

CREATE INDEX ix_crog_acquisition_properties_owner_id ON crog_acquisition.properties USING btree (owner_id);


--
-- Name: ix_crog_acquisition_properties_parcel_id; Type: INDEX; Schema: crog_acquisition; Owner: -
--

CREATE INDEX ix_crog_acquisition_properties_parcel_id ON crog_acquisition.properties USING btree (parcel_id);


--
-- Name: ix_dd_pipeline_id; Type: INDEX; Schema: crog_acquisition; Owner: -
--

CREATE INDEX ix_dd_pipeline_id ON crog_acquisition.due_diligence USING btree (pipeline_id);


--
-- Name: ix_dd_status; Type: INDEX; Schema: crog_acquisition; Owner: -
--

CREATE INDEX ix_dd_status ON crog_acquisition.due_diligence USING btree (status);


--
-- Name: ix_iot_schema_device_events_created_at; Type: INDEX; Schema: iot_schema; Owner: -
--

CREATE INDEX ix_iot_schema_device_events_created_at ON iot_schema.device_events USING btree (created_at);


--
-- Name: ix_iot_schema_device_events_device_id; Type: INDEX; Schema: iot_schema; Owner: -
--

CREATE INDEX ix_iot_schema_device_events_device_id ON iot_schema.device_events USING btree (device_id);


--
-- Name: ix_iot_schema_digital_twins_device_id; Type: INDEX; Schema: iot_schema; Owner: -
--

CREATE UNIQUE INDEX ix_iot_schema_digital_twins_device_id ON iot_schema.digital_twins USING btree (device_id);


--
-- Name: ix_iot_schema_digital_twins_property_id; Type: INDEX; Schema: iot_schema; Owner: -
--

CREATE INDEX ix_iot_schema_digital_twins_property_id ON iot_schema.digital_twins USING btree (property_id);


--
-- Name: idx_event_log_case_slug; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_event_log_case_slug ON legal.event_log USING btree (case_slug, emitted_at DESC) WHERE (case_slug IS NOT NULL);


--
-- Name: idx_event_log_event_type; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_event_log_event_type ON legal.event_log USING btree (event_type, emitted_at DESC);


--
-- Name: idx_event_log_unprocessed; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_event_log_unprocessed ON legal.event_log USING btree (emitted_at) WHERE (processed_at IS NULL);


--
-- Name: idx_mail_ingester_metrics_name_recorded; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_mail_ingester_metrics_name_recorded ON legal.mail_ingester_metrics USING btree (metric_name, recorded_at DESC);


--
-- Name: idx_priority_sender_rules_active; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_priority_sender_rules_active ON legal.priority_sender_rules USING btree (is_active, priority) WHERE (is_active = true);


--
-- Name: idx_priority_sender_rules_case_slug; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_priority_sender_rules_case_slug ON legal.priority_sender_rules USING btree (case_slug) WHERE (case_slug IS NOT NULL);


--
-- Name: ix_ai_audit_ledger_prompt_hash; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_ai_audit_ledger_prompt_hash ON legal.ai_audit_ledger USING btree (prompt_hash);


--
-- Name: ix_case_graph_nodes_case_id; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_case_graph_nodes_case_id ON legal.case_graph_nodes USING btree (case_id);


--
-- Name: ix_case_statements_slug; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_case_statements_slug ON legal.case_statements USING btree (case_slug);


--
-- Name: ix_legal_case_evidence_case_slug; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_case_evidence_case_slug ON legal.case_evidence USING btree (case_slug);


--
-- Name: ix_legal_case_evidence_entity_id; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_case_evidence_entity_id ON legal.case_evidence USING btree (entity_id);


--
-- Name: ix_legal_case_evidence_qdrant_point_id; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_case_evidence_qdrant_point_id ON legal.case_evidence USING btree (qdrant_point_id);


--
-- Name: ix_legal_case_evidence_sha256_hash; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_case_evidence_sha256_hash ON legal.case_evidence USING btree (sha256_hash);


--
-- Name: ix_legal_case_graph_edges_v2_case_slug; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_case_graph_edges_v2_case_slug ON legal.case_graph_edges_v2 USING btree (case_slug);


--
-- Name: ix_legal_case_graph_edges_v2_source_evidence_id; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_case_graph_edges_v2_source_evidence_id ON legal.case_graph_edges_v2 USING btree (source_evidence_id);


--
-- Name: ix_legal_case_graph_edges_v2_source_node_id; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_case_graph_edges_v2_source_node_id ON legal.case_graph_edges_v2 USING btree (source_node_id);


--
-- Name: ix_legal_case_graph_edges_v2_target_node_id; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_case_graph_edges_v2_target_node_id ON legal.case_graph_edges_v2 USING btree (target_node_id);


--
-- Name: ix_legal_case_graph_nodes_v2_case_slug; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_case_graph_nodes_v2_case_slug ON legal.case_graph_nodes_v2 USING btree (case_slug);


--
-- Name: ix_legal_case_graph_nodes_v2_entity_reference_id; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_case_graph_nodes_v2_entity_reference_id ON legal.case_graph_nodes_v2 USING btree (entity_reference_id);


--
-- Name: ix_legal_case_graph_nodes_v2_entity_type; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_case_graph_nodes_v2_entity_type ON legal.case_graph_nodes_v2 USING btree (entity_type);


--
-- Name: ix_legal_case_statements_v2_case_slug; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_case_statements_v2_case_slug ON legal.case_statements_v2 USING btree (case_slug);


--
-- Name: ix_legal_case_statements_v2_doc_id; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_case_statements_v2_doc_id ON legal.case_statements_v2 USING btree (doc_id);


--
-- Name: ix_legal_case_statements_v2_entity_id; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_case_statements_v2_entity_id ON legal.case_statements_v2 USING btree (entity_id);


--
-- Name: ix_legal_case_statements_v2_stated_at; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_case_statements_v2_stated_at ON legal.case_statements_v2 USING btree (stated_at);


--
-- Name: ix_legal_cases_slug; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_cases_slug ON legal.legal_cases USING btree (slug);


--
-- Name: ix_legal_deposition_kill_sheets_v2_case_slug; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_deposition_kill_sheets_v2_case_slug ON legal.deposition_kill_sheets_v2 USING btree (case_slug);


--
-- Name: ix_legal_deposition_kill_sheets_v2_deponent_entity; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_deposition_kill_sheets_v2_deponent_entity ON legal.deposition_kill_sheets_v2 USING btree (deponent_entity);


--
-- Name: ix_legal_deposition_kill_sheets_v2_status; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_deposition_kill_sheets_v2_status ON legal.deposition_kill_sheets_v2 USING btree (status);


--
-- Name: ix_legal_discovery_draft_items_v2_category; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_discovery_draft_items_v2_category ON legal.discovery_draft_items_v2 USING btree (category);


--
-- Name: ix_legal_discovery_draft_items_v2_pack_id; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_discovery_draft_items_v2_pack_id ON legal.discovery_draft_items_v2 USING btree (pack_id);


--
-- Name: ix_legal_discovery_draft_packs_v2_case_slug; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_discovery_draft_packs_v2_case_slug ON legal.discovery_draft_packs_v2 USING btree (case_slug);


--
-- Name: ix_legal_discovery_draft_packs_v2_status; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_discovery_draft_packs_v2_status ON legal.discovery_draft_packs_v2 USING btree (status);


--
-- Name: ix_legal_discovery_draft_packs_v2_target_entity; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_discovery_draft_packs_v2_target_entity ON legal.discovery_draft_packs_v2 USING btree (target_entity);


--
-- Name: ix_legal_distillation_memory_context_hash; Type: INDEX; Schema: legal; Owner: -
--

CREATE UNIQUE INDEX ix_legal_distillation_memory_context_hash ON legal.distillation_memory USING btree (context_hash);


--
-- Name: ix_legal_entities_name; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_entities_name ON legal.entities USING btree (name);


--
-- Name: ix_legal_entities_type; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_entities_type ON legal.entities USING btree (type);


--
-- Name: ix_legal_legal_exemplars_category; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_legal_exemplars_category ON legal.legal_exemplars USING btree (category);


--
-- Name: ix_legal_sanctions_alerts_v2_alert_type; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_sanctions_alerts_v2_alert_type ON legal.sanctions_alerts_v2 USING btree (alert_type);


--
-- Name: ix_legal_sanctions_alerts_v2_case_slug; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_sanctions_alerts_v2_case_slug ON legal.sanctions_alerts_v2 USING btree (case_slug);


--
-- Name: ix_legal_sanctions_alerts_v2_confidence_score; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_sanctions_alerts_v2_confidence_score ON legal.sanctions_alerts_v2 USING btree (confidence_score);


--
-- Name: ix_legal_sanctions_alerts_v2_status; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_sanctions_alerts_v2_status ON legal.sanctions_alerts_v2 USING btree (status);


--
-- Name: ix_legal_sanctions_tripwire_runs_v2_case_slug; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_sanctions_tripwire_runs_v2_case_slug ON legal.sanctions_tripwire_runs_v2 USING btree (case_slug);


--
-- Name: ix_legal_sanctions_tripwire_runs_v2_status; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_sanctions_tripwire_runs_v2_status ON legal.sanctions_tripwire_runs_v2 USING btree (status);


--
-- Name: ix_legal_sanctions_tripwire_runs_v2_trigger_source; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_sanctions_tripwire_runs_v2_trigger_source ON legal.sanctions_tripwire_runs_v2 USING btree (trigger_source);


--
-- Name: ix_legal_timeline_events_case_slug; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_timeline_events_case_slug ON legal.timeline_events USING btree (case_slug);


--
-- Name: ix_legal_timeline_events_event_date; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_timeline_events_event_date ON legal.timeline_events USING btree (event_date);


--
-- Name: ix_legal_timeline_events_source_evidence_id; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_timeline_events_source_evidence_id ON legal.timeline_events USING btree (source_evidence_id);


--
-- Name: ix_shadow_legal_cases_slug; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_shadow_legal_cases_slug ON legal.cases USING btree (case_slug);


--
-- Name: ix_vault_documents_slug; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_vault_documents_slug ON legal.vault_documents USING btree (case_slug);


--
-- Name: idx_cl_capture_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cl_capture_id ON public.capture_labels USING btree (capture_id);


--
-- Name: idx_cl_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cl_created_at ON public.capture_labels USING btree (created_at);


--
-- Name: idx_cl_godhead_decision; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cl_godhead_decision ON public.capture_labels USING btree (godhead_decision);


--
-- Name: idx_cl_qc_queue; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cl_qc_queue ON public.capture_labels USING btree (created_at DESC) WHERE ((qc_sampled = true) AND (qc_reviewed_at IS NULL));


--
-- Name: idx_cl_task_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cl_task_type ON public.capture_labels USING btree (task_type);


--
-- Name: idx_email_inquirers_guest_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_email_inquirers_guest_id ON public.email_inquirers USING btree (guest_id);


--
-- Name: idx_email_messages_imap_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_email_messages_imap_uid ON public.email_messages USING btree (imap_uid) WHERE (imap_uid IS NOT NULL);


--
-- Name: idx_email_messages_inquirer; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_email_messages_inquirer ON public.email_messages USING btree (inquirer_id, received_at DESC);


--
-- Name: idx_email_messages_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_email_messages_status ON public.email_messages USING btree (approval_status, received_at DESC);


--
-- Name: idx_email_messages_thread; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_email_messages_thread ON public.email_messages USING btree (in_reply_to_message_id);


--
-- Name: idx_llm_tc_judge_decision; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_llm_tc_judge_decision ON public.llm_training_captures USING btree (judge_decision);


--
-- Name: idx_llm_tc_served_by_endpoint; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_llm_tc_served_by_endpoint ON public.llm_training_captures USING btree (served_by_endpoint);


--
-- Name: idx_llm_tc_task_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_llm_tc_task_type ON public.llm_training_captures USING btree (task_type);


--
-- Name: idx_llm_tc_teacher_model; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_llm_tc_teacher_model ON public.llm_training_captures USING btree (teacher_model);


--
-- Name: idx_llm_training_captures_eval_holdout; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_llm_training_captures_eval_holdout ON public.llm_training_captures USING btree (eval_holdout);


--
-- Name: idx_rc_judge_decision; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rc_judge_decision ON public.restricted_captures USING btree (judge_decision);


--
-- Name: idx_rc_served_by_endpoint; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rc_served_by_endpoint ON public.restricted_captures USING btree (served_by_endpoint);


--
-- Name: idx_rc_task_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rc_task_type ON public.restricted_captures USING btree (task_type);


--
-- Name: idx_rc_teacher_model; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rc_teacher_model ON public.restricted_captures USING btree (teacher_model);


--
-- Name: idx_restricted_captures_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_restricted_captures_created_at ON public.restricted_captures USING btree (created_at);


--
-- Name: idx_restricted_captures_eval_holdout; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_restricted_captures_eval_holdout ON public.restricted_captures USING btree (eval_holdout);


--
-- Name: idx_restricted_captures_source_persona; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_restricted_captures_source_persona ON public.restricted_captures USING btree (source_persona);


--
-- Name: ix_accounts_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_accounts_code ON public.accounts USING btree (code);


--
-- Name: ix_activities_activity_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_activities_activity_slug ON public.activities USING btree (activity_slug);


--
-- Name: ix_activities_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_activities_slug ON public.activities USING btree (slug);


--
-- Name: ix_agent_queue_guest_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_queue_guest_id ON public.agent_queue USING btree (guest_id);


--
-- Name: ix_agent_queue_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_queue_property_id ON public.agent_queue USING btree (property_id);


--
-- Name: ix_agent_queue_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_queue_status ON public.agent_queue USING btree (status);


--
-- Name: ix_agent_queue_twilio_sid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_queue_twilio_sid ON public.agent_queue USING btree (twilio_sid);


--
-- Name: ix_agent_registry_is_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_registry_is_active ON public.agent_registry USING btree (is_active);


--
-- Name: ix_agent_registry_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_registry_name ON public.agent_registry USING btree (name);


--
-- Name: ix_agent_registry_role; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_registry_role ON public.agent_registry USING btree (role);


--
-- Name: ix_agent_response_queue_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_response_queue_created_at ON public.agent_response_queue USING btree (created_at);


--
-- Name: ix_agent_response_queue_guest_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_response_queue_guest_id ON public.agent_response_queue USING btree (guest_id);


--
-- Name: ix_agent_response_queue_intent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_response_queue_intent ON public.agent_response_queue USING btree (intent);


--
-- Name: ix_agent_response_queue_message_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_response_queue_message_id ON public.agent_response_queue USING btree (message_id);


--
-- Name: ix_agent_response_queue_reservation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_response_queue_reservation_id ON public.agent_response_queue USING btree (reservation_id);


--
-- Name: ix_agent_response_queue_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_response_queue_status ON public.agent_response_queue USING btree (status);


--
-- Name: ix_agent_runs_agent_status_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runs_agent_status_started ON public.agent_runs USING btree (agent_id, status, started_at);


--
-- Name: ix_agent_runs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runs_status ON public.agent_runs USING btree (status);


--
-- Name: ix_agent_runs_trigger_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runs_trigger_source ON public.agent_runs USING btree (trigger_source);


--
-- Name: ix_agent_runs_trigger_status_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runs_trigger_status_started ON public.agent_runs USING btree (trigger_source, status, started_at);


--
-- Name: ix_agreement_templates_agreement_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agreement_templates_agreement_type ON public.agreement_templates USING btree (agreement_type);


--
-- Name: ix_agreement_templates_is_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agreement_templates_is_active ON public.agreement_templates USING btree (is_active);


--
-- Name: ix_analytics_events_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_analytics_events_created_at ON public.analytics_events USING btree (created_at);


--
-- Name: ix_analytics_events_event_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_analytics_events_event_type ON public.analytics_events USING btree (event_type);


--
-- Name: ix_analytics_events_guest_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_analytics_events_guest_id ON public.analytics_events USING btree (guest_id);


--
-- Name: ix_analytics_events_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_analytics_events_property_id ON public.analytics_events USING btree (property_id);


--
-- Name: ix_analytics_events_reservation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_analytics_events_reservation_id ON public.analytics_events USING btree (reservation_id);


--
-- Name: ix_async_job_runs_arq_job_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_async_job_runs_arq_job_id ON public.async_job_runs USING btree (arq_job_id);


--
-- Name: ix_async_job_runs_job_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_async_job_runs_job_name ON public.async_job_runs USING btree (job_name);


--
-- Name: ix_async_job_runs_job_status_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_async_job_runs_job_status_created ON public.async_job_runs USING btree (job_name, status, created_at);


--
-- Name: ix_async_job_runs_queue_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_async_job_runs_queue_name ON public.async_job_runs USING btree (queue_name);


--
-- Name: ix_async_job_runs_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_async_job_runs_request_id ON public.async_job_runs USING btree (request_id);


--
-- Name: ix_async_job_runs_requested_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_async_job_runs_requested_by ON public.async_job_runs USING btree (requested_by);


--
-- Name: ix_async_job_runs_requested_by_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_async_job_runs_requested_by_created ON public.async_job_runs USING btree (requested_by, created_at);


--
-- Name: ix_async_job_runs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_async_job_runs_status ON public.async_job_runs USING btree (status);


--
-- Name: ix_async_job_runs_status_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_async_job_runs_status_created ON public.async_job_runs USING btree (status, created_at);


--
-- Name: ix_async_job_runs_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_async_job_runs_tenant_id ON public.async_job_runs USING btree (tenant_id);


--
-- Name: ix_blocked_days_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_blocked_days_property_id ON public.blocked_days USING btree (property_id);


--
-- Name: ix_blogs_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_blogs_slug ON public.blogs USING btree (slug);


--
-- Name: ix_channel_mappings_channel; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_channel_mappings_channel ON public.channel_mappings USING btree (channel);


--
-- Name: ix_channel_mappings_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_channel_mappings_property_id ON public.channel_mappings USING btree (property_id);


--
-- Name: ix_citation_records_directory_domain; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_citation_records_directory_domain ON public.citation_records USING btree (directory_domain);


--
-- Name: ix_citation_records_last_audited_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_citation_records_last_audited_at ON public.citation_records USING btree (last_audited_at);


--
-- Name: ix_citation_records_match_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_citation_records_match_status ON public.citation_records USING btree (match_status);


--
-- Name: ix_cleaners_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cleaners_active ON public.cleaners USING btree (active);


--
-- Name: ix_competitor_listings_dedupe_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_competitor_listings_dedupe_hash ON public.competitor_listings USING btree (dedupe_hash);


--
-- Name: ix_competitor_listings_last_observed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_competitor_listings_last_observed ON public.competitor_listings USING btree (last_observed);


--
-- Name: ix_competitor_listings_platform; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_competitor_listings_platform ON public.competitor_listings USING btree (platform);


--
-- Name: ix_competitor_listings_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_competitor_listings_property_id ON public.competitor_listings USING btree (property_id);


--
-- Name: ix_competitor_listings_property_platform_observed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_competitor_listings_property_platform_observed ON public.competitor_listings USING btree (property_id, platform, last_observed);


--
-- Name: ix_concierge_queue_guest_phone; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_concierge_queue_guest_phone ON public.concierge_queue USING btree (guest_phone);


--
-- Name: ix_concierge_queue_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_concierge_queue_property_id ON public.concierge_queue USING btree (property_id);


--
-- Name: ix_concierge_queue_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_concierge_queue_status ON public.concierge_queue USING btree (status);


--
-- Name: ix_concierge_queue_status_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_concierge_queue_status_created ON public.concierge_queue USING btree (status, created_at);


--
-- Name: ix_crd_guest_channel_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_crd_guest_channel_created ON public.concierge_recovery_dispatches USING btree (guest_id, channel, created_at);


--
-- Name: ix_crd_session_fp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_crd_session_fp ON public.concierge_recovery_dispatches USING btree (session_fp);


--
-- Name: ix_damage_claims_guest_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_damage_claims_guest_id ON public.damage_claims USING btree (guest_id);


--
-- Name: ix_damage_claims_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_damage_claims_property_id ON public.damage_claims USING btree (property_id);


--
-- Name: ix_damage_claims_reservation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_damage_claims_reservation_id ON public.damage_claims USING btree (reservation_id);


--
-- Name: ix_deferred_api_writes_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_deferred_api_writes_created_at ON public.deferred_api_writes USING btree (created_at);


--
-- Name: ix_deferred_api_writes_service; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_deferred_api_writes_service ON public.deferred_api_writes USING btree (service);


--
-- Name: ix_deferred_api_writes_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_deferred_api_writes_status ON public.deferred_api_writes USING btree (status);


--
-- Name: ix_distillation_queue_source_intelligence_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_distillation_queue_source_intelligence_id ON public.distillation_queue USING btree (source_intelligence_id);


--
-- Name: ix_distillation_queue_source_module; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_distillation_queue_source_module ON public.distillation_queue USING btree (source_module);


--
-- Name: ix_distillation_queue_source_ref; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_distillation_queue_source_ref ON public.distillation_queue USING btree (source_ref);


--
-- Name: ix_distillation_queue_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_distillation_queue_status ON public.distillation_queue USING btree (status);


--
-- Name: ix_email_templates_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_email_templates_name ON public.email_templates USING btree (name);


--
-- Name: ix_email_templates_trigger_event; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_email_templates_trigger_event ON public.email_templates USING btree (trigger_event);


--
-- Name: ix_extra_orders_extra_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extra_orders_extra_id ON public.extra_orders USING btree (extra_id);


--
-- Name: ix_extra_orders_reservation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extra_orders_reservation_id ON public.extra_orders USING btree (reservation_id);


--
-- Name: ix_extra_orders_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extra_orders_status ON public.extra_orders USING btree (status);


--
-- Name: ix_extras_is_available; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extras_is_available ON public.extras USING btree (is_available);


--
-- Name: ix_fees_name; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_fees_name ON public.fees USING btree (name);


--
-- Name: ix_financial_approvals_reservation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_financial_approvals_reservation_id ON public.financial_approvals USING btree (reservation_id);


--
-- Name: ix_financial_approvals_resolution_strategy; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_financial_approvals_resolution_strategy ON public.financial_approvals USING btree (resolution_strategy);


--
-- Name: ix_financial_approvals_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_financial_approvals_status ON public.financial_approvals USING btree (status);


--
-- Name: ix_functional_nodes_canonical_path; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_functional_nodes_canonical_path ON public.functional_nodes USING btree (canonical_path);


--
-- Name: ix_functional_nodes_content_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_functional_nodes_content_category ON public.functional_nodes USING btree (content_category);


--
-- Name: ix_functional_nodes_crawl_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_functional_nodes_crawl_status ON public.functional_nodes USING btree (crawl_status);


--
-- Name: ix_functional_nodes_cutover_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_functional_nodes_cutover_status ON public.functional_nodes USING btree (cutover_status);


--
-- Name: ix_functional_nodes_functional_complexity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_functional_nodes_functional_complexity ON public.functional_nodes USING btree (functional_complexity);


--
-- Name: ix_functional_nodes_is_published; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_functional_nodes_is_published ON public.functional_nodes USING btree (is_published);


--
-- Name: ix_functional_nodes_legacy_node_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_functional_nodes_legacy_node_id ON public.functional_nodes USING btree (legacy_node_id);


--
-- Name: ix_functional_nodes_mirror_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_functional_nodes_mirror_status ON public.functional_nodes USING btree (mirror_status);


--
-- Name: ix_functional_nodes_node_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_functional_nodes_node_type ON public.functional_nodes USING btree (node_type);


--
-- Name: ix_functional_nodes_priority_tier; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_functional_nodes_priority_tier ON public.functional_nodes USING btree (priority_tier);


--
-- Name: ix_functional_nodes_source_path; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_functional_nodes_source_path ON public.functional_nodes USING btree (source_path);


--
-- Name: ix_guest_activities_activity_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guest_activities_activity_type ON public.guest_activities USING btree (activity_type);


--
-- Name: ix_guest_activities_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guest_activities_category ON public.guest_activities USING btree (category);


--
-- Name: ix_guest_activities_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guest_activities_created_at ON public.guest_activities USING btree (created_at);


--
-- Name: ix_guest_activities_guest_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guest_activities_guest_id ON public.guest_activities USING btree (guest_id);


--
-- Name: ix_guest_quotes_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guest_quotes_property_id ON public.guest_quotes USING btree (property_id);


--
-- Name: ix_guest_quotes_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guest_quotes_status ON public.guest_quotes USING btree (status);


--
-- Name: ix_guest_quotes_status_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guest_quotes_status_created ON public.guest_quotes USING btree (status, created_at);


--
-- Name: ix_guest_quotes_target_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guest_quotes_target_property_id ON public.guest_quotes USING btree (target_property_id);


--
-- Name: ix_guest_reviews_direction; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guest_reviews_direction ON public.guest_reviews USING btree (direction);


--
-- Name: ix_guest_reviews_guest_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guest_reviews_guest_id ON public.guest_reviews USING btree (guest_id);


--
-- Name: ix_guest_reviews_is_published; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guest_reviews_is_published ON public.guest_reviews USING btree (is_published);


--
-- Name: ix_guest_reviews_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guest_reviews_property_id ON public.guest_reviews USING btree (property_id);


--
-- Name: ix_guest_reviews_reservation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guest_reviews_reservation_id ON public.guest_reviews USING btree (reservation_id);


--
-- Name: ix_guest_surveys_guest_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guest_surveys_guest_id ON public.guest_surveys USING btree (guest_id);


--
-- Name: ix_guest_surveys_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guest_surveys_property_id ON public.guest_surveys USING btree (property_id);


--
-- Name: ix_guest_surveys_reservation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guest_surveys_reservation_id ON public.guest_surveys USING btree (reservation_id);


--
-- Name: ix_guest_surveys_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guest_surveys_status ON public.guest_surveys USING btree (status);


--
-- Name: ix_guest_surveys_survey_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guest_surveys_survey_type ON public.guest_surveys USING btree (survey_type);


--
-- Name: ix_guest_surveys_template_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guest_surveys_template_id ON public.guest_surveys USING btree (template_id);


--
-- Name: ix_guest_verifications_guest_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guest_verifications_guest_id ON public.guest_verifications USING btree (guest_id);


--
-- Name: ix_guest_verifications_reservation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guest_verifications_reservation_id ON public.guest_verifications USING btree (reservation_id);


--
-- Name: ix_guest_verifications_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guest_verifications_status ON public.guest_verifications USING btree (status);


--
-- Name: ix_guestbook_guides_guide_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guestbook_guides_guide_type ON public.guestbook_guides USING btree (guide_type);


--
-- Name: ix_guestbook_guides_is_visible; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guestbook_guides_is_visible ON public.guestbook_guides USING btree (is_visible);


--
-- Name: ix_guestbook_guides_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guestbook_guides_property_id ON public.guestbook_guides USING btree (property_id);


--
-- Name: ix_guests_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guests_email ON public.guests USING btree (email);


--
-- Name: ix_guests_guest_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guests_guest_source ON public.guests USING btree (guest_source);


--
-- Name: ix_guests_is_blacklisted; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guests_is_blacklisted ON public.guests USING btree (is_blacklisted);


--
-- Name: ix_guests_is_vip; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guests_is_vip ON public.guests USING btree (is_vip);


--
-- Name: ix_guests_loyalty_tier; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guests_loyalty_tier ON public.guests USING btree (loyalty_tier);


--
-- Name: ix_guests_phone; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_guests_phone ON public.guests USING btree (phone);


--
-- Name: ix_guests_verification_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_guests_verification_status ON public.guests USING btree (verification_status);


--
-- Name: ix_housekeeping_tasks_cleaner; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_housekeeping_tasks_cleaner ON public.housekeeping_tasks USING btree (assigned_cleaner_id);


--
-- Name: ix_housekeeping_tasks_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_housekeeping_tasks_property_id ON public.housekeeping_tasks USING btree (property_id);


--
-- Name: ix_housekeeping_tasks_reservation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_housekeeping_tasks_reservation_id ON public.housekeeping_tasks USING btree (reservation_id);


--
-- Name: ix_housekeeping_tasks_scheduled_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_housekeeping_tasks_scheduled_date ON public.housekeeping_tasks USING btree (scheduled_date);


--
-- Name: ix_housekeeping_tasks_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_housekeeping_tasks_status ON public.housekeeping_tasks USING btree (status);


--
-- Name: ix_hunter_queue_guest_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_hunter_queue_guest_email ON public.hunter_queue USING btree (guest_email);


--
-- Name: ix_hunter_queue_guest_phone; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_hunter_queue_guest_phone ON public.hunter_queue USING btree (guest_phone);


--
-- Name: ix_hunter_queue_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_hunter_queue_property_id ON public.hunter_queue USING btree (property_id);


--
-- Name: ix_hunter_queue_reservation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_hunter_queue_reservation_id ON public.hunter_queue USING btree (reservation_id);


--
-- Name: ix_hunter_queue_session_fp; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_hunter_queue_session_fp ON public.hunter_queue USING btree (session_fp);


--
-- Name: ix_hunter_queue_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_hunter_queue_status ON public.hunter_queue USING btree (status);


--
-- Name: ix_hunter_queue_status_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_hunter_queue_status_created ON public.hunter_queue USING btree (status, created_at);


--
-- Name: ix_hunter_recovery_ops_cart_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_hunter_recovery_ops_cart_id ON public.hunter_recovery_ops USING btree (cart_id);


--
-- Name: ix_hunter_recovery_ops_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_hunter_recovery_ops_status ON public.hunter_recovery_ops USING btree (status);


--
-- Name: ix_hunter_recovery_ops_status_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_hunter_recovery_ops_status_created ON public.hunter_recovery_ops USING btree (status, created_at);


--
-- Name: ix_intelligence_ledger_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intelligence_ledger_category ON public.intelligence_ledger USING btree (category);


--
-- Name: ix_intelligence_ledger_category_discovered; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intelligence_ledger_category_discovered ON public.intelligence_ledger USING btree (category, discovered_at);


--
-- Name: ix_intelligence_ledger_dedupe_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intelligence_ledger_dedupe_hash ON public.intelligence_ledger USING btree (dedupe_hash);


--
-- Name: ix_intelligence_ledger_discovered_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intelligence_ledger_discovered_at ON public.intelligence_ledger USING btree (discovered_at);


--
-- Name: ix_intelligence_ledger_locality; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intelligence_ledger_locality ON public.intelligence_ledger USING btree (locality);


--
-- Name: ix_intelligence_ledger_market; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intelligence_ledger_market ON public.intelligence_ledger USING btree (market);


--
-- Name: ix_intelligence_ledger_market_discovered; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intelligence_ledger_market_discovered ON public.intelligence_ledger USING btree (market, discovered_at);


--
-- Name: ix_intelligence_ledger_query_topic; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intelligence_ledger_query_topic ON public.intelligence_ledger USING btree (query_topic);


--
-- Name: ix_intelligence_ledger_scout_run_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intelligence_ledger_scout_run_key ON public.intelligence_ledger USING btree (scout_run_key);


--
-- Name: ix_journal_entries_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_journal_entries_property_id ON public.journal_entries USING btree (property_id);


--
-- Name: ix_journal_entries_reference; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_journal_entries_reference ON public.journal_entries USING btree (reference_type, reference_id);


--
-- Name: ix_journal_line_items_journal_entry_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_journal_line_items_journal_entry_id ON public.journal_line_items USING btree (journal_entry_id);


--
-- Name: ix_knowledge_base_entries_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_base_entries_category ON public.knowledge_base_entries USING btree (category);


--
-- Name: ix_knowledge_base_entries_is_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_base_entries_is_active ON public.knowledge_base_entries USING btree (is_active);


--
-- Name: ix_knowledge_base_entries_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_base_entries_property_id ON public.knowledge_base_entries USING btree (property_id);


--
-- Name: ix_leads_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_leads_email ON public.leads USING btree (email);


--
-- Name: ix_leads_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_leads_source ON public.leads USING btree (source);


--
-- Name: ix_leads_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_leads_status ON public.leads USING btree (status);


--
-- Name: ix_leads_streamline_lead_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_leads_streamline_lead_id ON public.leads USING btree (streamline_lead_id);


--
-- Name: ix_learned_rules_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_learned_rules_property_id ON public.learned_rules USING btree (property_id);


--
-- Name: ix_learned_rules_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_learned_rules_status ON public.learned_rules USING btree (status);


--
-- Name: ix_legacy_pages_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_legacy_pages_slug ON public.legacy_pages USING btree (slug);


--
-- Name: ix_legal_case_statements_case_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_legal_case_statements_case_slug ON public.legal_case_statements USING btree (case_slug);


--
-- Name: ix_legal_case_statements_entity_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_legal_case_statements_entity_name ON public.legal_case_statements USING btree (entity_name);


--
-- Name: ix_legal_case_statements_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_legal_case_statements_id ON public.legal_case_statements USING btree (id);


--
-- Name: ix_legal_hive_mind_feedback_events_case_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_legal_hive_mind_feedback_events_case_slug ON public.legal_hive_mind_feedback_events USING btree (case_slug);


--
-- Name: ix_legal_hive_mind_feedback_events_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_legal_hive_mind_feedback_events_id ON public.legal_hive_mind_feedback_events USING btree (id);


--
-- Name: ix_legal_hive_mind_feedback_events_module_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_legal_hive_mind_feedback_events_module_type ON public.legal_hive_mind_feedback_events USING btree (module_type);


--
-- Name: ix_llm_training_captures_module; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_llm_training_captures_module ON public.llm_training_captures USING btree (source_module);


--
-- Name: ix_llm_training_captures_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_llm_training_captures_status ON public.llm_training_captures USING btree (status);


--
-- Name: ix_management_splits_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_management_splits_property_id ON public.management_splits USING btree (property_id);


--
-- Name: ix_marketing_articles_category_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_marketing_articles_category_id ON public.marketing_articles USING btree (category_id);


--
-- Name: ix_marketing_articles_published_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_marketing_articles_published_date ON public.marketing_articles USING btree (published_date);


--
-- Name: ix_marketing_articles_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_marketing_articles_slug ON public.marketing_articles USING btree (slug);


--
-- Name: ix_message_queue_quote_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_message_queue_quote_id ON public.message_queue USING btree (quote_id);


--
-- Name: ix_message_queue_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_message_queue_status ON public.message_queue USING btree (status);


--
-- Name: ix_message_queue_template_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_message_queue_template_id ON public.message_queue USING btree (template_id);


--
-- Name: ix_message_templates_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_message_templates_category ON public.message_templates USING btree (category);


--
-- Name: ix_message_templates_is_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_message_templates_is_active ON public.message_templates USING btree (is_active);


--
-- Name: ix_messages_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_messages_created_at ON public.messages USING btree (created_at);


--
-- Name: ix_messages_direction; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_messages_direction ON public.messages USING btree (direction);


--
-- Name: ix_messages_external_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_messages_external_id ON public.messages USING btree (external_id);


--
-- Name: ix_messages_guest_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_messages_guest_id ON public.messages USING btree (guest_id);


--
-- Name: ix_messages_intent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_messages_intent ON public.messages USING btree (intent);


--
-- Name: ix_messages_phone_from; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_messages_phone_from ON public.messages USING btree (phone_from);


--
-- Name: ix_messages_reservation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_messages_reservation_id ON public.messages USING btree (reservation_id);


--
-- Name: ix_messages_sentiment; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_messages_sentiment ON public.messages USING btree (sentiment);


--
-- Name: ix_obp_owner_period; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_obp_owner_period ON public.owner_balance_periods USING btree (owner_payout_account_id, period_start);


--
-- Name: ix_obp_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_obp_status ON public.owner_balance_periods USING btree (status);


--
-- Name: ix_obp_stripe_transfer_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_obp_stripe_transfer_id ON public.owner_balance_periods USING btree (stripe_transfer_id) WHERE (stripe_transfer_id IS NOT NULL);


--
-- Name: ix_oc_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_oc_active ON public.owner_charges USING btree (owner_payout_account_id, posting_date) WHERE (voided_at IS NULL);


--
-- Name: ix_oc_owner_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_oc_owner_date ON public.owner_charges USING btree (owner_payout_account_id, posting_date);


--
-- Name: ix_oc_transaction_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_oc_transaction_type ON public.owner_charges USING btree (transaction_type);


--
-- Name: ix_opa_streamline_owner_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_opa_streamline_owner_id ON public.owner_payout_accounts USING btree (streamline_owner_id);


--
-- Name: ix_openshell_audit_logs_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_openshell_audit_logs_action ON public.openshell_audit_logs USING btree (action);


--
-- Name: ix_openshell_audit_logs_actor_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_openshell_audit_logs_actor_id ON public.openshell_audit_logs USING btree (actor_id);


--
-- Name: ix_openshell_audit_logs_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_openshell_audit_logs_created_at ON public.openshell_audit_logs USING btree (created_at);


--
-- Name: ix_openshell_audit_logs_entry_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_openshell_audit_logs_entry_hash ON public.openshell_audit_logs USING btree (entry_hash);


--
-- Name: ix_openshell_audit_logs_model_route; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_openshell_audit_logs_model_route ON public.openshell_audit_logs USING btree (model_route);


--
-- Name: ix_openshell_audit_logs_outcome; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_openshell_audit_logs_outcome ON public.openshell_audit_logs USING btree (outcome);


--
-- Name: ix_openshell_audit_logs_payload_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_openshell_audit_logs_payload_hash ON public.openshell_audit_logs USING btree (payload_hash);


--
-- Name: ix_openshell_audit_logs_prev_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_openshell_audit_logs_prev_hash ON public.openshell_audit_logs USING btree (prev_hash);


--
-- Name: ix_openshell_audit_logs_redaction_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_openshell_audit_logs_redaction_status ON public.openshell_audit_logs USING btree (redaction_status);


--
-- Name: ix_openshell_audit_logs_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_openshell_audit_logs_request_id ON public.openshell_audit_logs USING btree (request_id);


--
-- Name: ix_openshell_audit_logs_resource_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_openshell_audit_logs_resource_type ON public.openshell_audit_logs USING btree (resource_type);


--
-- Name: ix_openshell_audit_logs_tool_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_openshell_audit_logs_tool_name ON public.openshell_audit_logs USING btree (tool_name);


--
-- Name: ix_operator_overrides_escalation_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_operator_overrides_escalation_timestamp ON public.operator_overrides USING btree (escalation_id, "timestamp");


--
-- Name: ix_operator_overrides_operator_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_operator_overrides_operator_email ON public.operator_overrides USING btree (operator_email);


--
-- Name: ix_operator_overrides_operator_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_operator_overrides_operator_timestamp ON public.operator_overrides USING btree (operator_email, "timestamp");


--
-- Name: ix_operator_overrides_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_operator_overrides_timestamp ON public.operator_overrides USING btree ("timestamp");


--
-- Name: ix_oss_owner_payout_account_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_oss_owner_payout_account_id ON public.owner_statement_sends USING btree (owner_payout_account_id);


--
-- Name: ix_oss_period; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_oss_period ON public.owner_statement_sends USING btree (statement_period_start, statement_period_end);


--
-- Name: ix_oss_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_oss_property_id ON public.owner_statement_sends USING btree (property_id);


--
-- Name: ix_oss_sent_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_oss_sent_at ON public.owner_statement_sends USING btree (sent_at);


--
-- Name: ix_ota_micro_updates_channel; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ota_micro_updates_channel ON public.ota_micro_updates USING btree (channel);


--
-- Name: ix_ota_micro_updates_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ota_micro_updates_property_id ON public.ota_micro_updates USING btree (property_id);


--
-- Name: ix_ota_micro_updates_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ota_micro_updates_status ON public.ota_micro_updates USING btree (status);


--
-- Name: ix_owner_charges_vendor_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_owner_charges_vendor_id ON public.owner_charges USING btree (vendor_id);


--
-- Name: ix_owner_payout_accounts_owner_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_owner_payout_accounts_owner_email ON public.owner_payout_accounts USING btree (owner_email);


--
-- Name: ix_owner_payout_accounts_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_owner_payout_accounts_status ON public.owner_payout_accounts USING btree (account_status);


--
-- Name: ix_parity_audits_confirmation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_parity_audits_confirmation_id ON public.parity_audits USING btree (confirmation_id);


--
-- Name: ix_parity_audits_reservation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_parity_audits_reservation_id ON public.parity_audits USING btree (reservation_id);


--
-- Name: ix_parity_audits_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_parity_audits_status ON public.parity_audits USING btree (status);


--
-- Name: ix_payout_ledger_confirmation_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_payout_ledger_confirmation_code ON public.payout_ledger USING btree (confirmation_code);


--
-- Name: ix_payout_ledger_property_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_payout_ledger_property_created ON public.payout_ledger USING btree (property_id, created_at DESC);


--
-- Name: ix_payout_ledger_status_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_payout_ledger_status_created ON public.payout_ledger USING btree (status, created_at DESC);


--
-- Name: ix_pending_sync_reservation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pending_sync_reservation_id ON public.pending_sync USING btree (reservation_id);


--
-- Name: ix_pending_sync_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pending_sync_status ON public.pending_sync USING btree (status);


--
-- Name: ix_pricing_overrides_property_dates; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pricing_overrides_property_dates ON public.pricing_overrides USING btree (property_id, start_date, end_date);


--
-- Name: ix_pricing_overrides_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pricing_overrides_property_id ON public.pricing_overrides USING btree (property_id);


--
-- Name: ix_properties_renting_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_properties_renting_state ON public.properties USING btree (renting_state);


--
-- Name: ix_properties_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_properties_slug ON public.properties USING btree (slug);


--
-- Name: ix_properties_streamline_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_properties_streamline_property_id ON public.properties USING btree (streamline_property_id);


--
-- Name: ix_property_fees_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_property_fees_property_id ON public.property_fees USING btree (property_id);


--
-- Name: ix_property_images_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_property_images_property_id ON public.property_images USING btree (property_id);


--
-- Name: ix_property_images_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_property_images_status ON public.property_images USING btree (status);


--
-- Name: ix_property_knowledge_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_property_knowledge_category ON public.property_knowledge USING btree (category);


--
-- Name: ix_property_knowledge_chunks_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_property_knowledge_chunks_property_id ON public.property_knowledge_chunks USING btree (property_id);


--
-- Name: ix_property_knowledge_prop_cat_updated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_property_knowledge_prop_cat_updated ON public.property_knowledge USING btree (property_id, category, updated_at);


--
-- Name: ix_property_knowledge_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_property_knowledge_property_id ON public.property_knowledge USING btree (property_id);


--
-- Name: ix_property_knowledge_updated_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_property_knowledge_updated_at ON public.property_knowledge USING btree (updated_at);


--
-- Name: ix_property_stay_restrictions_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_property_stay_restrictions_property_id ON public.property_stay_restrictions USING btree (property_id);


--
-- Name: ix_property_taxes_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_property_taxes_property_id ON public.property_taxes USING btree (property_id);


--
-- Name: ix_property_utilities_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_property_utilities_property_id ON public.property_utilities USING btree (property_id);


--
-- Name: ix_quote_options_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_quote_options_property_id ON public.quote_options USING btree (property_id);


--
-- Name: ix_quote_options_quote_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_quote_options_quote_id ON public.quote_options USING btree (quote_id);


--
-- Name: ix_quotes_lead_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_quotes_lead_id ON public.quotes USING btree (lead_id);


--
-- Name: ix_quotes_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_quotes_status ON public.quotes USING btree (status);


--
-- Name: ix_recovery_parity_comparisons_async_job_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recovery_parity_comparisons_async_job_run_id ON public.recovery_parity_comparisons USING btree (async_job_run_id);


--
-- Name: ix_recovery_parity_comparisons_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recovery_parity_comparisons_created_at ON public.recovery_parity_comparisons USING btree (created_at);


--
-- Name: ix_recovery_parity_comparisons_dedupe_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recovery_parity_comparisons_dedupe_hash ON public.recovery_parity_comparisons USING btree (dedupe_hash);


--
-- Name: ix_recovery_parity_comparisons_guest_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recovery_parity_comparisons_guest_id ON public.recovery_parity_comparisons USING btree (guest_id);


--
-- Name: ix_recovery_parity_comparisons_session_fp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recovery_parity_comparisons_session_fp ON public.recovery_parity_comparisons USING btree (session_fp);


--
-- Name: ix_recovery_parity_guest_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recovery_parity_guest_created ON public.recovery_parity_comparisons USING btree (guest_id, created_at);


--
-- Name: ix_recovery_parity_session_fp_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recovery_parity_session_fp_created ON public.recovery_parity_comparisons USING btree (session_fp, created_at);


--
-- Name: ix_rental_agreements_guest_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rental_agreements_guest_id ON public.rental_agreements USING btree (guest_id);


--
-- Name: ix_rental_agreements_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rental_agreements_property_id ON public.rental_agreements USING btree (property_id);


--
-- Name: ix_rental_agreements_reservation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rental_agreements_reservation_id ON public.rental_agreements USING btree (reservation_id);


--
-- Name: ix_rental_agreements_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rental_agreements_status ON public.rental_agreements USING btree (status);


--
-- Name: ix_rental_agreements_template_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rental_agreements_template_id ON public.rental_agreements USING btree (template_id);


--
-- Name: ix_reservation_holds_converted_reservation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reservation_holds_converted_reservation_id ON public.reservation_holds USING btree (converted_reservation_id);


--
-- Name: ix_reservation_holds_guest_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reservation_holds_guest_id ON public.reservation_holds USING btree (guest_id);


--
-- Name: ix_reservation_holds_payment_intent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reservation_holds_payment_intent_id ON public.reservation_holds USING btree (payment_intent_id);


--
-- Name: ix_reservation_holds_property_dates; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reservation_holds_property_dates ON public.reservation_holds USING btree (property_id, check_in_date, check_out_date);


--
-- Name: ix_reservation_holds_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reservation_holds_property_id ON public.reservation_holds USING btree (property_id);


--
-- Name: ix_reservation_holds_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reservation_holds_session_id ON public.reservation_holds USING btree (session_id);


--
-- Name: ix_reservation_holds_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reservation_holds_status ON public.reservation_holds USING btree (status);


--
-- Name: ix_reservation_holds_status_expires; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reservation_holds_status_expires ON public.reservation_holds USING btree (status, expires_at);


--
-- Name: ix_reservations_check_in_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reservations_check_in_date ON public.reservations USING btree (check_in_date);


--
-- Name: ix_reservations_check_out_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reservations_check_out_date ON public.reservations USING btree (check_out_date);


--
-- Name: ix_reservations_confirmation_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_reservations_confirmation_code ON public.reservations USING btree (confirmation_code);


--
-- Name: ix_reservations_guest_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reservations_guest_email ON public.reservations USING btree (guest_email);


--
-- Name: ix_reservations_guest_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reservations_guest_id ON public.reservations USING btree (guest_id);


--
-- Name: ix_reservations_is_owner_booking; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reservations_is_owner_booking ON public.reservations USING btree (is_owner_booking);


--
-- Name: ix_reservations_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reservations_property_id ON public.reservations USING btree (property_id);


--
-- Name: ix_reservations_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reservations_status ON public.reservations USING btree (status);


--
-- Name: ix_rue_bar_rue_legacy_recovery_templates_audience_rule; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rue_bar_rue_legacy_recovery_templates_audience_rule ON public.rue_bar_rue_legacy_recovery_templates USING btree (audience_rule);


--
-- Name: ix_rue_bar_rue_legacy_recovery_templates_channel; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rue_bar_rue_legacy_recovery_templates_channel ON public.rue_bar_rue_legacy_recovery_templates USING btree (channel);


--
-- Name: ix_rue_bar_rue_legacy_recovery_templates_template_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rue_bar_rue_legacy_recovery_templates_template_key ON public.rue_bar_rue_legacy_recovery_templates USING btree (template_key);


--
-- Name: ix_scheduled_messages_guest_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scheduled_messages_guest_id ON public.scheduled_messages USING btree (guest_id);


--
-- Name: ix_scheduled_messages_reservation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scheduled_messages_reservation_id ON public.scheduled_messages USING btree (reservation_id);


--
-- Name: ix_scheduled_messages_scheduled_for; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scheduled_messages_scheduled_for ON public.scheduled_messages USING btree (scheduled_for);


--
-- Name: ix_scheduled_messages_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scheduled_messages_status ON public.scheduled_messages USING btree (status);


--
-- Name: ix_scheduled_messages_template_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scheduled_messages_template_id ON public.scheduled_messages USING btree (template_id);


--
-- Name: ix_seo_patch_queue_campaign; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_patch_queue_campaign ON public.seo_patch_queue USING btree (campaign);


--
-- Name: ix_seo_patch_queue_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_patch_queue_created_at ON public.seo_patch_queue USING btree (created_at);


--
-- Name: ix_seo_patch_queue_property_approved; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_patch_queue_property_approved ON public.seo_patch_queue USING btree (property_id, approved_at);


--
-- Name: ix_seo_patch_queue_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_patch_queue_property_id ON public.seo_patch_queue USING btree (property_id);


--
-- Name: ix_seo_patch_queue_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_patch_queue_status ON public.seo_patch_queue USING btree (status);


--
-- Name: ix_seo_patch_queue_status_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_patch_queue_status_created ON public.seo_patch_queue USING btree (status, created_at);


--
-- Name: ix_seo_patch_queue_target_approved; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_patch_queue_target_approved ON public.seo_patch_queue USING btree (target_type, target_slug, approved_at);


--
-- Name: ix_seo_patch_queue_target_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_patch_queue_target_slug ON public.seo_patch_queue USING btree (target_slug);


--
-- Name: ix_seo_patch_queue_target_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_patch_queue_target_type ON public.seo_patch_queue USING btree (target_type);


--
-- Name: ix_seo_patches_deploy_acknowledged_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_patches_deploy_acknowledged_at ON public.seo_patches USING btree (deploy_acknowledged_at);


--
-- Name: ix_seo_patches_deploy_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_patches_deploy_status ON public.seo_patches USING btree (deploy_status);


--
-- Name: ix_seo_patches_deployed_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_patches_deployed_at ON public.seo_patches USING btree (deployed_at);


--
-- Name: ix_seo_patches_page_path; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_patches_page_path ON public.seo_patches USING btree (page_path);


--
-- Name: ix_seo_patches_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_patches_property_id ON public.seo_patches USING btree (property_id);


--
-- Name: ix_seo_patches_rubric_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_patches_rubric_id ON public.seo_patches USING btree (rubric_id);


--
-- Name: ix_seo_patches_source_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_patches_source_agent ON public.seo_patches USING btree (source_agent);


--
-- Name: ix_seo_patches_source_intelligence_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_patches_source_intelligence_id ON public.seo_patches USING btree (source_intelligence_id);


--
-- Name: ix_seo_patches_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_patches_status ON public.seo_patches USING btree (status);


--
-- Name: ix_seo_rank_snapshots_keyword; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_rank_snapshots_keyword ON public.seo_rank_snapshots USING btree (keyword);


--
-- Name: ix_seo_rank_snapshots_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_rank_snapshots_property_id ON public.seo_rank_snapshots USING btree (property_id);


--
-- Name: ix_seo_rank_snapshots_snapshot_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_rank_snapshots_snapshot_date ON public.seo_rank_snapshots USING btree (snapshot_date);


--
-- Name: ix_seo_redirect_remap_queue_campaign; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_redirect_remap_queue_campaign ON public.seo_redirect_remap_queue USING btree (campaign);


--
-- Name: ix_seo_redirect_remap_queue_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_redirect_remap_queue_created_at ON public.seo_redirect_remap_queue USING btree (created_at);


--
-- Name: ix_seo_redirect_remap_queue_proposal_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_redirect_remap_queue_proposal_run_id ON public.seo_redirect_remap_queue USING btree (proposal_run_id);


--
-- Name: ix_seo_redirect_remap_queue_source_path; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_redirect_remap_queue_source_path ON public.seo_redirect_remap_queue USING btree (source_path);


--
-- Name: ix_seo_redirect_remap_queue_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_redirect_remap_queue_status ON public.seo_redirect_remap_queue USING btree (status);


--
-- Name: ix_seo_redirect_remap_queue_status_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_redirect_remap_queue_status_created ON public.seo_redirect_remap_queue USING btree (status, created_at);


--
-- Name: ix_seo_redirects_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_redirects_created_at ON public.seo_redirects USING btree (created_at);


--
-- Name: ix_seo_redirects_is_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_redirects_is_active ON public.seo_redirects USING btree (is_active);


--
-- Name: ix_seo_redirects_source_path; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_seo_redirects_source_path ON public.seo_redirects USING btree (source_path);


--
-- Name: ix_seo_rubrics_keyword_cluster; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_rubrics_keyword_cluster ON public.seo_rubrics USING btree (keyword_cluster);


--
-- Name: ix_seo_rubrics_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_seo_rubrics_status ON public.seo_rubrics USING btree (status);


--
-- Name: ix_shadow_discrepancies_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_shadow_discrepancies_property_id ON public.shadow_discrepancies USING btree (property_id);


--
-- Name: ix_shadow_discrepancies_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_shadow_discrepancies_status ON public.shadow_discrepancies USING btree (status);


--
-- Name: ix_ssgl_guest_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ssgl_guest_id ON public.storefront_session_guest_links USING btree (guest_id);


--
-- Name: ix_ssgl_session_fp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ssgl_session_fp ON public.storefront_session_guest_links USING btree (session_fp);


--
-- Name: ix_ssgl_session_fp_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ssgl_session_fp_created ON public.storefront_session_guest_links USING btree (session_fp, created_at);


--
-- Name: ix_staff_invites_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_staff_invites_email ON public.staff_invites USING btree (email);


--
-- Name: ix_staff_invites_token; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_staff_invites_token ON public.staff_invites USING btree (token);


--
-- Name: ix_staff_users_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_staff_users_email ON public.staff_users USING btree (email);


--
-- Name: ix_staff_users_role; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_staff_users_role ON public.staff_users USING btree (role);


--
-- Name: ix_storefront_intent_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_storefront_intent_created ON public.storefront_intent_events USING btree (created_at);


--
-- Name: ix_storefront_intent_events_session_fp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_storefront_intent_events_session_fp ON public.storefront_intent_events USING btree (session_fp);


--
-- Name: ix_storefront_intent_session_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_storefront_intent_session_created ON public.storefront_intent_events USING btree (session_fp, created_at);


--
-- Name: ix_streamline_payload_vault_event_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_streamline_payload_vault_event_type ON public.streamline_payload_vault USING btree (event_type);


--
-- Name: ix_streamline_payload_vault_reservation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_streamline_payload_vault_reservation_id ON public.streamline_payload_vault USING btree (reservation_id);


--
-- Name: ix_stripe_connect_events_account_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_stripe_connect_events_account_id ON public.stripe_connect_events USING btree (account_id);


--
-- Name: ix_stripe_connect_events_event_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_stripe_connect_events_event_type ON public.stripe_connect_events USING btree (event_type);


--
-- Name: ix_stripe_connect_events_payout_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_stripe_connect_events_payout_id ON public.stripe_connect_events USING btree (payout_id);


--
-- Name: ix_stripe_connect_events_transfer_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_stripe_connect_events_transfer_id ON public.stripe_connect_events USING btree (transfer_id);


--
-- Name: ix_survey_templates_is_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_survey_templates_is_active ON public.survey_templates USING btree (is_active);


--
-- Name: ix_survey_templates_survey_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_survey_templates_survey_type ON public.survey_templates USING btree (survey_type);


--
-- Name: ix_swarm_escalations_reason_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_swarm_escalations_reason_code ON public.swarm_escalations USING btree (reason_code);


--
-- Name: ix_swarm_escalations_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_swarm_escalations_status ON public.swarm_escalations USING btree (status);


--
-- Name: ix_swarm_escalations_status_reason; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_swarm_escalations_status_reason ON public.swarm_escalations USING btree (status, reason_code);


--
-- Name: ix_taxes_name; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_taxes_name ON public.taxes USING btree (name);


--
-- Name: ix_taxonomy_categories_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_taxonomy_categories_slug ON public.taxonomy_categories USING btree (slug);


--
-- Name: ix_taylor_quote_requests_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_taylor_quote_requests_created_at ON public.taylor_quote_requests USING btree (created_at DESC);


--
-- Name: ix_taylor_quote_requests_guest_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_taylor_quote_requests_guest_email ON public.taylor_quote_requests USING btree (guest_email);


--
-- Name: ix_taylor_quote_requests_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_taylor_quote_requests_status ON public.taylor_quote_requests USING btree (status);


--
-- Name: ix_trust_accounts_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_trust_accounts_name ON public.trust_accounts USING btree (name);


--
-- Name: ix_trust_accounts_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_trust_accounts_type ON public.trust_accounts USING btree (type);


--
-- Name: ix_trust_accounts_type_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_trust_accounts_type_name ON public.trust_accounts USING btree (type, name);


--
-- Name: ix_trust_decisions_run_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_trust_decisions_run_status ON public.trust_decisions USING btree (run_id, status);


--
-- Name: ix_trust_decisions_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_trust_decisions_status ON public.trust_decisions USING btree (status);


--
-- Name: ix_trust_ledger_entries_account_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_trust_ledger_entries_account_id ON public.trust_ledger_entries USING btree (account_id);


--
-- Name: ix_trust_ledger_entries_entry_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_trust_ledger_entries_entry_type ON public.trust_ledger_entries USING btree (entry_type);


--
-- Name: ix_trust_ledger_entries_transaction_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_trust_ledger_entries_transaction_id ON public.trust_ledger_entries USING btree (transaction_id);


--
-- Name: ix_trust_transactions_decision_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_trust_transactions_decision_timestamp ON public.trust_transactions USING btree (decision_id, "timestamp");


--
-- Name: ix_trust_transactions_previous_signature; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_trust_transactions_previous_signature ON public.trust_transactions USING btree (previous_signature);


--
-- Name: ix_trust_transactions_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_trust_transactions_timestamp ON public.trust_transactions USING btree ("timestamp");


--
-- Name: ix_utility_readings_utility_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_utility_readings_utility_id ON public.utility_readings USING btree (utility_id);


--
-- Name: ix_vault_audit_logs_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vault_audit_logs_action ON public.vault_audit_logs USING btree (action);


--
-- Name: ix_vault_audit_logs_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vault_audit_logs_created_at ON public.vault_audit_logs USING btree (created_at);


--
-- Name: ix_vault_audit_logs_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vault_audit_logs_user_id ON public.vault_audit_logs USING btree (user_id);


--
-- Name: ix_vendors_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vendors_active ON public.vendors USING btree (active);


--
-- Name: ix_vendors_trade; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vendors_trade ON public.vendors USING btree (trade);


--
-- Name: ix_vrs_add_ons_active_scope_property; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vrs_add_ons_active_scope_property ON public.vrs_add_ons USING btree (is_active, scope, property_id);


--
-- Name: ix_vrs_add_ons_is_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vrs_add_ons_is_active ON public.vrs_add_ons USING btree (is_active);


--
-- Name: ix_vrs_add_ons_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vrs_add_ons_property_id ON public.vrs_add_ons USING btree (property_id);


--
-- Name: ix_vrs_add_ons_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vrs_add_ons_scope ON public.vrs_add_ons USING btree (scope);


--
-- Name: ix_vrs_automation_events_entity_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vrs_automation_events_entity_id ON public.vrs_automation_events USING btree (entity_id);


--
-- Name: ix_vrs_automation_events_entity_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vrs_automation_events_entity_type ON public.vrs_automation_events USING btree (entity_type);


--
-- Name: ix_vrs_automation_events_event_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vrs_automation_events_event_type ON public.vrs_automation_events USING btree (event_type);


--
-- Name: ix_vrs_automation_events_rule_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vrs_automation_events_rule_id ON public.vrs_automation_events USING btree (rule_id);


--
-- Name: ix_vrs_automations_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vrs_automations_name ON public.vrs_automations USING btree (name);


--
-- Name: ix_vrs_automations_target_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vrs_automations_target_entity ON public.vrs_automations USING btree (target_entity);


--
-- Name: ix_vrs_automations_trigger_event; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vrs_automations_trigger_event ON public.vrs_automations USING btree (trigger_event);


--
-- Name: ix_work_orders_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_work_orders_created_at ON public.work_orders USING btree (created_at);


--
-- Name: ix_work_orders_guest_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_work_orders_guest_id ON public.work_orders USING btree (guest_id);


--
-- Name: ix_work_orders_priority; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_work_orders_priority ON public.work_orders USING btree (priority);


--
-- Name: ix_work_orders_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_work_orders_property_id ON public.work_orders USING btree (property_id);


--
-- Name: ix_work_orders_reservation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_work_orders_reservation_id ON public.work_orders USING btree (reservation_id);


--
-- Name: ix_work_orders_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_work_orders_status ON public.work_orders USING btree (status);


--
-- Name: ix_work_orders_vendor; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_work_orders_vendor ON public.work_orders USING btree (assigned_vendor_id);


--
-- Name: ix_yield_overrides_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_yield_overrides_property_id ON public.yield_overrides USING btree (property_id);


--
-- Name: ix_yield_simulations_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_yield_simulations_property_id ON public.yield_simulations USING btree (property_id);


--
-- Name: uq_payout_ledger_stripe_transfer_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_payout_ledger_stripe_transfer_id ON public.payout_ledger USING btree (stripe_transfer_id) WHERE (stripe_transfer_id IS NOT NULL);


--
-- Name: ix_verses_schema_products_sku; Type: INDEX; Schema: verses_schema; Owner: -
--

CREATE UNIQUE INDEX ix_verses_schema_products_sku ON verses_schema.products USING btree (sku);


--
-- Name: streamline_payload_vault trg_immutable_streamline_payload_vault; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_immutable_streamline_payload_vault BEFORE DELETE OR UPDATE ON public.streamline_payload_vault FOR EACH ROW EXECUTE FUNCTION public.prevent_mutation();


--
-- Name: trust_ledger_entries trg_immutable_trust_ledger_entries; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_immutable_trust_ledger_entries BEFORE DELETE OR UPDATE ON public.trust_ledger_entries FOR EACH ROW EXECUTE FUNCTION public.prevent_mutation();


--
-- Name: trust_transactions trg_immutable_trust_transactions; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_immutable_trust_transactions BEFORE DELETE OR UPDATE ON public.trust_transactions FOR EACH ROW EXECUTE FUNCTION public.prevent_mutation();


--
-- Name: acquisition_documents acquisition_documents_pipeline_id_fkey; Type: FK CONSTRAINT; Schema: crog_acquisition; Owner: -
--

ALTER TABLE ONLY crog_acquisition.acquisition_documents
    ADD CONSTRAINT acquisition_documents_pipeline_id_fkey FOREIGN KEY (pipeline_id) REFERENCES crog_acquisition.acquisition_pipeline(id) ON DELETE CASCADE;


--
-- Name: acquisition_pipeline acquisition_pipeline_property_id_fkey; Type: FK CONSTRAINT; Schema: crog_acquisition; Owner: -
--

ALTER TABLE ONLY crog_acquisition.acquisition_pipeline
    ADD CONSTRAINT acquisition_pipeline_property_id_fkey FOREIGN KEY (property_id) REFERENCES crog_acquisition.properties(id) ON DELETE CASCADE;


--
-- Name: due_diligence due_diligence_pipeline_id_fkey; Type: FK CONSTRAINT; Schema: crog_acquisition; Owner: -
--

ALTER TABLE ONLY crog_acquisition.due_diligence
    ADD CONSTRAINT due_diligence_pipeline_id_fkey FOREIGN KEY (pipeline_id) REFERENCES crog_acquisition.acquisition_pipeline(id) ON DELETE CASCADE;


--
-- Name: intel_events intel_events_property_id_fkey; Type: FK CONSTRAINT; Schema: crog_acquisition; Owner: -
--

ALTER TABLE ONLY crog_acquisition.intel_events
    ADD CONSTRAINT intel_events_property_id_fkey FOREIGN KEY (property_id) REFERENCES crog_acquisition.properties(id) ON DELETE CASCADE;


--
-- Name: owner_contacts owner_contacts_owner_id_fkey; Type: FK CONSTRAINT; Schema: crog_acquisition; Owner: -
--

ALTER TABLE ONLY crog_acquisition.owner_contacts
    ADD CONSTRAINT owner_contacts_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES crog_acquisition.owners(id) ON DELETE CASCADE;


--
-- Name: properties properties_owner_id_fkey; Type: FK CONSTRAINT; Schema: crog_acquisition; Owner: -
--

ALTER TABLE ONLY crog_acquisition.properties
    ADD CONSTRAINT properties_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES crog_acquisition.owners(id) ON DELETE SET NULL;


--
-- Name: properties properties_parcel_id_fkey; Type: FK CONSTRAINT; Schema: crog_acquisition; Owner: -
--

ALTER TABLE ONLY crog_acquisition.properties
    ADD CONSTRAINT properties_parcel_id_fkey FOREIGN KEY (parcel_id) REFERENCES crog_acquisition.parcels(id) ON DELETE CASCADE;


--
-- Name: str_signals str_signals_property_id_fkey; Type: FK CONSTRAINT; Schema: crog_acquisition; Owner: -
--

ALTER TABLE ONLY crog_acquisition.str_signals
    ADD CONSTRAINT str_signals_property_id_fkey FOREIGN KEY (property_id) REFERENCES crog_acquisition.properties(id) ON DELETE CASCADE;


--
-- Name: case_evidence case_evidence_entity_id_fkey; Type: FK CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.case_evidence
    ADD CONSTRAINT case_evidence_entity_id_fkey FOREIGN KEY (entity_id) REFERENCES legal.entities(id) ON DELETE SET NULL;


--
-- Name: case_graph_edges case_graph_edges_case_id_fkey; Type: FK CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.case_graph_edges
    ADD CONSTRAINT case_graph_edges_case_id_fkey FOREIGN KEY (case_id) REFERENCES legal.legal_cases(id) ON DELETE CASCADE;


--
-- Name: case_graph_edges case_graph_edges_source_node_id_fkey; Type: FK CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.case_graph_edges
    ADD CONSTRAINT case_graph_edges_source_node_id_fkey FOREIGN KEY (source_node_id) REFERENCES legal.case_graph_nodes(id) ON DELETE CASCADE;


--
-- Name: case_graph_edges case_graph_edges_target_node_id_fkey; Type: FK CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.case_graph_edges
    ADD CONSTRAINT case_graph_edges_target_node_id_fkey FOREIGN KEY (target_node_id) REFERENCES legal.case_graph_nodes(id) ON DELETE CASCADE;


--
-- Name: case_graph_edges_v2 case_graph_edges_v2_source_node_id_fkey; Type: FK CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.case_graph_edges_v2
    ADD CONSTRAINT case_graph_edges_v2_source_node_id_fkey FOREIGN KEY (source_node_id) REFERENCES legal.case_graph_nodes_v2(id) ON DELETE CASCADE;


--
-- Name: case_graph_edges_v2 case_graph_edges_v2_target_node_id_fkey; Type: FK CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.case_graph_edges_v2
    ADD CONSTRAINT case_graph_edges_v2_target_node_id_fkey FOREIGN KEY (target_node_id) REFERENCES legal.case_graph_nodes_v2(id) ON DELETE CASCADE;


--
-- Name: case_graph_nodes case_graph_nodes_case_id_fkey; Type: FK CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.case_graph_nodes
    ADD CONSTRAINT case_graph_nodes_case_id_fkey FOREIGN KEY (case_id) REFERENCES legal.legal_cases(id) ON DELETE CASCADE;


--
-- Name: discovery_draft_items_v2 discovery_draft_items_v2_pack_id_fkey; Type: FK CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.discovery_draft_items_v2
    ADD CONSTRAINT discovery_draft_items_v2_pack_id_fkey FOREIGN KEY (pack_id) REFERENCES legal.discovery_draft_packs_v2(id) ON DELETE CASCADE;


--
-- Name: timeline_events timeline_events_source_evidence_id_fkey; Type: FK CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.timeline_events
    ADD CONSTRAINT timeline_events_source_evidence_id_fkey FOREIGN KEY (source_evidence_id) REFERENCES legal.case_evidence(id) ON DELETE SET NULL;


--
-- Name: agent_queue agent_queue_guest_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_queue
    ADD CONSTRAINT agent_queue_guest_id_fkey FOREIGN KEY (guest_id) REFERENCES public.guests(id) ON DELETE SET NULL;


--
-- Name: agent_queue agent_queue_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_queue
    ADD CONSTRAINT agent_queue_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE SET NULL;


--
-- Name: agent_response_queue agent_response_queue_guest_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_response_queue
    ADD CONSTRAINT agent_response_queue_guest_id_fkey FOREIGN KEY (guest_id) REFERENCES public.guests(id) ON DELETE SET NULL;


--
-- Name: agent_response_queue agent_response_queue_message_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_response_queue
    ADD CONSTRAINT agent_response_queue_message_id_fkey FOREIGN KEY (message_id) REFERENCES public.messages(id) ON DELETE CASCADE;


--
-- Name: agent_response_queue agent_response_queue_reservation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_response_queue
    ADD CONSTRAINT agent_response_queue_reservation_id_fkey FOREIGN KEY (reservation_id) REFERENCES public.reservations(id) ON DELETE SET NULL;


--
-- Name: agent_response_queue agent_response_queue_sent_message_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_response_queue
    ADD CONSTRAINT agent_response_queue_sent_message_id_fkey FOREIGN KEY (sent_message_id) REFERENCES public.messages(id) ON DELETE SET NULL;


--
-- Name: agent_runs agent_runs_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT agent_runs_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agent_registry(id) ON DELETE RESTRICT;


--
-- Name: analytics_events analytics_events_guest_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.analytics_events
    ADD CONSTRAINT analytics_events_guest_id_fkey FOREIGN KEY (guest_id) REFERENCES public.guests(id) ON DELETE SET NULL;


--
-- Name: analytics_events analytics_events_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.analytics_events
    ADD CONSTRAINT analytics_events_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE SET NULL;


--
-- Name: analytics_events analytics_events_reservation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.analytics_events
    ADD CONSTRAINT analytics_events_reservation_id_fkey FOREIGN KEY (reservation_id) REFERENCES public.reservations(id) ON DELETE SET NULL;


--
-- Name: blocked_days blocked_days_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.blocked_days
    ADD CONSTRAINT blocked_days_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- Name: channel_mappings channel_mappings_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channel_mappings
    ADD CONSTRAINT channel_mappings_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- Name: competitor_listings competitor_listings_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.competitor_listings
    ADD CONSTRAINT competitor_listings_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- Name: concierge_queue concierge_queue_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.concierge_queue
    ADD CONSTRAINT concierge_queue_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE SET NULL;


--
-- Name: concierge_recovery_dispatches concierge_recovery_dispatches_guest_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.concierge_recovery_dispatches
    ADD CONSTRAINT concierge_recovery_dispatches_guest_id_fkey FOREIGN KEY (guest_id) REFERENCES public.guests(id) ON DELETE CASCADE;


--
-- Name: damage_claims damage_claims_guest_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.damage_claims
    ADD CONSTRAINT damage_claims_guest_id_fkey FOREIGN KEY (guest_id) REFERENCES public.guests(id) ON DELETE CASCADE;


--
-- Name: damage_claims damage_claims_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.damage_claims
    ADD CONSTRAINT damage_claims_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- Name: damage_claims damage_claims_rental_agreement_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.damage_claims
    ADD CONSTRAINT damage_claims_rental_agreement_id_fkey FOREIGN KEY (rental_agreement_id) REFERENCES public.rental_agreements(id) ON DELETE SET NULL;


--
-- Name: damage_claims damage_claims_reservation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.damage_claims
    ADD CONSTRAINT damage_claims_reservation_id_fkey FOREIGN KEY (reservation_id) REFERENCES public.reservations(id) ON DELETE CASCADE;


--
-- Name: distillation_queue distillation_queue_source_intelligence_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.distillation_queue
    ADD CONSTRAINT distillation_queue_source_intelligence_id_fkey FOREIGN KEY (source_intelligence_id) REFERENCES public.intelligence_ledger(id) ON DELETE SET NULL;


--
-- Name: email_inquirers email_inquirers_guest_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_inquirers
    ADD CONSTRAINT email_inquirers_guest_id_fkey FOREIGN KEY (guest_id) REFERENCES public.guests(id) ON DELETE SET NULL;


--
-- Name: email_messages email_messages_guest_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_messages
    ADD CONSTRAINT email_messages_guest_id_fkey FOREIGN KEY (guest_id) REFERENCES public.guests(id) ON DELETE SET NULL;


--
-- Name: email_messages email_messages_human_reviewed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_messages
    ADD CONSTRAINT email_messages_human_reviewed_by_fkey FOREIGN KEY (human_reviewed_by) REFERENCES public.staff_users(id) ON DELETE SET NULL;


--
-- Name: email_messages email_messages_inquirer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_messages
    ADD CONSTRAINT email_messages_inquirer_id_fkey FOREIGN KEY (inquirer_id) REFERENCES public.email_inquirers(id) ON DELETE CASCADE;


--
-- Name: email_messages email_messages_reservation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_messages
    ADD CONSTRAINT email_messages_reservation_id_fkey FOREIGN KEY (reservation_id) REFERENCES public.reservations(id) ON DELETE SET NULL;


--
-- Name: extra_orders extra_orders_extra_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extra_orders
    ADD CONSTRAINT extra_orders_extra_id_fkey FOREIGN KEY (extra_id) REFERENCES public.extras(id) ON DELETE CASCADE;


--
-- Name: extra_orders extra_orders_reservation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extra_orders
    ADD CONSTRAINT extra_orders_reservation_id_fkey FOREIGN KEY (reservation_id) REFERENCES public.reservations(id) ON DELETE CASCADE;


--
-- Name: email_messages fk_email_messages_reply_to; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_messages
    ADD CONSTRAINT fk_email_messages_reply_to FOREIGN KEY (in_reply_to_message_id) REFERENCES public.email_messages(id) ON DELETE SET NULL;


--
-- Name: guest_activities guest_activities_guest_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.guest_activities
    ADD CONSTRAINT guest_activities_guest_id_fkey FOREIGN KEY (guest_id) REFERENCES public.guests(id) ON DELETE CASCADE;


--
-- Name: guest_activities guest_activities_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.guest_activities
    ADD CONSTRAINT guest_activities_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE SET NULL;


--
-- Name: guest_activities guest_activities_reservation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.guest_activities
    ADD CONSTRAINT guest_activities_reservation_id_fkey FOREIGN KEY (reservation_id) REFERENCES public.reservations(id) ON DELETE SET NULL;


--
-- Name: guest_quotes guest_quotes_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.guest_quotes
    ADD CONSTRAINT guest_quotes_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE SET NULL;


--
-- Name: guest_reviews guest_reviews_guest_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.guest_reviews
    ADD CONSTRAINT guest_reviews_guest_id_fkey FOREIGN KEY (guest_id) REFERENCES public.guests(id) ON DELETE CASCADE;


--
-- Name: guest_reviews guest_reviews_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.guest_reviews
    ADD CONSTRAINT guest_reviews_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- Name: guest_reviews guest_reviews_reservation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.guest_reviews
    ADD CONSTRAINT guest_reviews_reservation_id_fkey FOREIGN KEY (reservation_id) REFERENCES public.reservations(id) ON DELETE SET NULL;


--
-- Name: guest_surveys guest_surveys_guest_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.guest_surveys
    ADD CONSTRAINT guest_surveys_guest_id_fkey FOREIGN KEY (guest_id) REFERENCES public.guests(id) ON DELETE CASCADE;


--
-- Name: guest_surveys guest_surveys_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.guest_surveys
    ADD CONSTRAINT guest_surveys_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE SET NULL;


--
-- Name: guest_surveys guest_surveys_reservation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.guest_surveys
    ADD CONSTRAINT guest_surveys_reservation_id_fkey FOREIGN KEY (reservation_id) REFERENCES public.reservations(id) ON DELETE SET NULL;


--
-- Name: guest_surveys guest_surveys_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.guest_surveys
    ADD CONSTRAINT guest_surveys_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.survey_templates(id) ON DELETE SET NULL;


--
-- Name: guest_verifications guest_verifications_guest_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.guest_verifications
    ADD CONSTRAINT guest_verifications_guest_id_fkey FOREIGN KEY (guest_id) REFERENCES public.guests(id) ON DELETE CASCADE;


--
-- Name: guest_verifications guest_verifications_reservation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.guest_verifications
    ADD CONSTRAINT guest_verifications_reservation_id_fkey FOREIGN KEY (reservation_id) REFERENCES public.reservations(id) ON DELETE SET NULL;


--
-- Name: guestbook_guides guestbook_guides_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.guestbook_guides
    ADD CONSTRAINT guestbook_guides_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- Name: housekeeping_tasks housekeeping_tasks_assigned_cleaner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.housekeeping_tasks
    ADD CONSTRAINT housekeeping_tasks_assigned_cleaner_id_fkey FOREIGN KEY (assigned_cleaner_id) REFERENCES public.cleaners(id) ON DELETE SET NULL;


--
-- Name: housekeeping_tasks housekeeping_tasks_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.housekeeping_tasks
    ADD CONSTRAINT housekeeping_tasks_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- Name: housekeeping_tasks housekeeping_tasks_reservation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.housekeeping_tasks
    ADD CONSTRAINT housekeeping_tasks_reservation_id_fkey FOREIGN KEY (reservation_id) REFERENCES public.reservations(id) ON DELETE SET NULL;


--
-- Name: hunter_queue hunter_queue_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hunter_queue
    ADD CONSTRAINT hunter_queue_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE SET NULL;


--
-- Name: hunter_queue hunter_queue_reservation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hunter_queue
    ADD CONSTRAINT hunter_queue_reservation_id_fkey FOREIGN KEY (reservation_id) REFERENCES public.reservations(id) ON DELETE SET NULL;


--
-- Name: journal_line_items journal_line_items_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_line_items
    ADD CONSTRAINT journal_line_items_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.accounts(id) ON DELETE RESTRICT;


--
-- Name: journal_line_items journal_line_items_journal_entry_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_line_items
    ADD CONSTRAINT journal_line_items_journal_entry_id_fkey FOREIGN KEY (journal_entry_id) REFERENCES public.journal_entries(id) ON DELETE CASCADE;


--
-- Name: knowledge_base_entries knowledge_base_entries_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_base_entries
    ADD CONSTRAINT knowledge_base_entries_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- Name: marketing_articles marketing_articles_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.marketing_articles
    ADD CONSTRAINT marketing_articles_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.taxonomy_categories(id) ON DELETE CASCADE;


--
-- Name: message_queue message_queue_quote_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_queue
    ADD CONSTRAINT message_queue_quote_id_fkey FOREIGN KEY (quote_id) REFERENCES public.quotes(id) ON DELETE CASCADE;


--
-- Name: message_queue message_queue_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_queue
    ADD CONSTRAINT message_queue_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.email_templates(id) ON DELETE CASCADE;


--
-- Name: messages messages_guest_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_guest_id_fkey FOREIGN KEY (guest_id) REFERENCES public.guests(id) ON DELETE SET NULL;


--
-- Name: messages messages_reservation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_reservation_id_fkey FOREIGN KEY (reservation_id) REFERENCES public.reservations(id) ON DELETE SET NULL;


--
-- Name: operator_overrides operator_overrides_escalation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.operator_overrides
    ADD CONSTRAINT operator_overrides_escalation_id_fkey FOREIGN KEY (escalation_id) REFERENCES public.swarm_escalations(id) ON DELETE CASCADE;


--
-- Name: ota_micro_updates ota_micro_updates_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ota_micro_updates
    ADD CONSTRAINT ota_micro_updates_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- Name: owner_balance_periods owner_balance_periods_owner_payout_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_balance_periods
    ADD CONSTRAINT owner_balance_periods_owner_payout_account_id_fkey FOREIGN KEY (owner_payout_account_id) REFERENCES public.owner_payout_accounts(id) ON DELETE RESTRICT;


--
-- Name: owner_charges owner_charges_owner_payout_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_charges
    ADD CONSTRAINT owner_charges_owner_payout_account_id_fkey FOREIGN KEY (owner_payout_account_id) REFERENCES public.owner_payout_accounts(id) ON DELETE RESTRICT;


--
-- Name: owner_charges owner_charges_vendor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_charges
    ADD CONSTRAINT owner_charges_vendor_id_fkey FOREIGN KEY (vendor_id) REFERENCES public.vendors(id) ON DELETE SET NULL;


--
-- Name: owner_statement_sends owner_statement_sends_owner_payout_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_statement_sends
    ADD CONSTRAINT owner_statement_sends_owner_payout_account_id_fkey FOREIGN KEY (owner_payout_account_id) REFERENCES public.owner_payout_accounts(id) ON DELETE RESTRICT;


--
-- Name: owner_statement_sends owner_statement_sends_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_statement_sends
    ADD CONSTRAINT owner_statement_sends_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE RESTRICT;


--
-- Name: pricing_overrides pricing_overrides_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pricing_overrides
    ADD CONSTRAINT pricing_overrides_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- Name: properties properties_default_housekeeper_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.properties
    ADD CONSTRAINT properties_default_housekeeper_id_fkey FOREIGN KEY (default_housekeeper_id) REFERENCES public.staff_users(id) ON DELETE SET NULL;


--
-- Name: property_fees property_fees_fee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.property_fees
    ADD CONSTRAINT property_fees_fee_id_fkey FOREIGN KEY (fee_id) REFERENCES public.fees(id) ON DELETE CASCADE;


--
-- Name: property_fees property_fees_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.property_fees
    ADD CONSTRAINT property_fees_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- Name: property_images property_images_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.property_images
    ADD CONSTRAINT property_images_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- Name: property_knowledge_chunks property_knowledge_chunks_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.property_knowledge_chunks
    ADD CONSTRAINT property_knowledge_chunks_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- Name: property_knowledge property_knowledge_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.property_knowledge
    ADD CONSTRAINT property_knowledge_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- Name: property_stay_restrictions property_stay_restrictions_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.property_stay_restrictions
    ADD CONSTRAINT property_stay_restrictions_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- Name: property_taxes property_taxes_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.property_taxes
    ADD CONSTRAINT property_taxes_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- Name: property_taxes property_taxes_tax_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.property_taxes
    ADD CONSTRAINT property_taxes_tax_id_fkey FOREIGN KEY (tax_id) REFERENCES public.taxes(id) ON DELETE CASCADE;


--
-- Name: property_utilities property_utilities_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.property_utilities
    ADD CONSTRAINT property_utilities_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- Name: quote_options quote_options_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quote_options
    ADD CONSTRAINT quote_options_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- Name: quote_options quote_options_quote_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quote_options
    ADD CONSTRAINT quote_options_quote_id_fkey FOREIGN KEY (quote_id) REFERENCES public.quotes(id) ON DELETE CASCADE;


--
-- Name: quotes quotes_lead_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotes
    ADD CONSTRAINT quotes_lead_id_fkey FOREIGN KEY (lead_id) REFERENCES public.leads(id) ON DELETE CASCADE;


--
-- Name: recovery_parity_comparisons recovery_parity_comparisons_guest_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recovery_parity_comparisons
    ADD CONSTRAINT recovery_parity_comparisons_guest_id_fkey FOREIGN KEY (guest_id) REFERENCES public.guests(id) ON DELETE SET NULL;


--
-- Name: rental_agreements rental_agreements_guest_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rental_agreements
    ADD CONSTRAINT rental_agreements_guest_id_fkey FOREIGN KEY (guest_id) REFERENCES public.guests(id) ON DELETE CASCADE;


--
-- Name: rental_agreements rental_agreements_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rental_agreements
    ADD CONSTRAINT rental_agreements_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE SET NULL;


--
-- Name: rental_agreements rental_agreements_reservation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rental_agreements
    ADD CONSTRAINT rental_agreements_reservation_id_fkey FOREIGN KEY (reservation_id) REFERENCES public.reservations(id) ON DELETE SET NULL;


--
-- Name: rental_agreements rental_agreements_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rental_agreements
    ADD CONSTRAINT rental_agreements_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.agreement_templates(id) ON DELETE SET NULL;


--
-- Name: reservation_holds reservation_holds_converted_reservation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reservation_holds
    ADD CONSTRAINT reservation_holds_converted_reservation_id_fkey FOREIGN KEY (converted_reservation_id) REFERENCES public.reservations(id) ON DELETE SET NULL;


--
-- Name: reservation_holds reservation_holds_guest_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reservation_holds
    ADD CONSTRAINT reservation_holds_guest_id_fkey FOREIGN KEY (guest_id) REFERENCES public.guests(id) ON DELETE CASCADE;


--
-- Name: reservation_holds reservation_holds_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reservation_holds
    ADD CONSTRAINT reservation_holds_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- Name: reservations reservations_guest_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reservations
    ADD CONSTRAINT reservations_guest_id_fkey FOREIGN KEY (guest_id) REFERENCES public.guests(id) ON DELETE CASCADE;


--
-- Name: reservations reservations_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reservations
    ADD CONSTRAINT reservations_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- Name: scheduled_messages scheduled_messages_guest_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_messages
    ADD CONSTRAINT scheduled_messages_guest_id_fkey FOREIGN KEY (guest_id) REFERENCES public.guests(id) ON DELETE CASCADE;


--
-- Name: scheduled_messages scheduled_messages_message_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_messages
    ADD CONSTRAINT scheduled_messages_message_id_fkey FOREIGN KEY (message_id) REFERENCES public.messages(id) ON DELETE SET NULL;


--
-- Name: scheduled_messages scheduled_messages_reservation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_messages
    ADD CONSTRAINT scheduled_messages_reservation_id_fkey FOREIGN KEY (reservation_id) REFERENCES public.reservations(id) ON DELETE CASCADE;


--
-- Name: scheduled_messages scheduled_messages_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_messages
    ADD CONSTRAINT scheduled_messages_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.message_templates(id) ON DELETE CASCADE;


--
-- Name: seo_patch_queue seo_patch_queue_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.seo_patch_queue
    ADD CONSTRAINT seo_patch_queue_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- Name: seo_patches seo_patches_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.seo_patches
    ADD CONSTRAINT seo_patches_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- Name: seo_patches seo_patches_rubric_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.seo_patches
    ADD CONSTRAINT seo_patches_rubric_id_fkey FOREIGN KEY (rubric_id) REFERENCES public.seo_rubrics(id) ON DELETE SET NULL;


--
-- Name: seo_patches seo_patches_source_intelligence_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.seo_patches
    ADD CONSTRAINT seo_patches_source_intelligence_id_fkey FOREIGN KEY (source_intelligence_id) REFERENCES public.intelligence_ledger(id) ON DELETE SET NULL;


--
-- Name: seo_rank_snapshots seo_rank_snapshots_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.seo_rank_snapshots
    ADD CONSTRAINT seo_rank_snapshots_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- Name: staff_invites staff_invites_invited_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staff_invites
    ADD CONSTRAINT staff_invites_invited_by_fkey FOREIGN KEY (invited_by) REFERENCES public.staff_users(id);


--
-- Name: storefront_session_guest_links storefront_session_guest_links_guest_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.storefront_session_guest_links
    ADD CONSTRAINT storefront_session_guest_links_guest_id_fkey FOREIGN KEY (guest_id) REFERENCES public.guests(id) ON DELETE CASCADE;


--
-- Name: storefront_session_guest_links storefront_session_guest_links_reservation_hold_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.storefront_session_guest_links
    ADD CONSTRAINT storefront_session_guest_links_reservation_hold_id_fkey FOREIGN KEY (reservation_hold_id) REFERENCES public.reservation_holds(id) ON DELETE SET NULL;


--
-- Name: swarm_escalations swarm_escalations_decision_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.swarm_escalations
    ADD CONSTRAINT swarm_escalations_decision_id_fkey FOREIGN KEY (decision_id) REFERENCES public.trust_decisions(id) ON DELETE CASCADE;


--
-- Name: trust_decisions trust_decisions_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trust_decisions
    ADD CONSTRAINT trust_decisions_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.agent_runs(id) ON DELETE CASCADE;


--
-- Name: trust_ledger_entries trust_ledger_entries_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trust_ledger_entries
    ADD CONSTRAINT trust_ledger_entries_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.trust_accounts(id) ON DELETE RESTRICT;


--
-- Name: trust_ledger_entries trust_ledger_entries_transaction_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trust_ledger_entries
    ADD CONSTRAINT trust_ledger_entries_transaction_id_fkey FOREIGN KEY (transaction_id) REFERENCES public.trust_transactions(id) ON DELETE CASCADE;


--
-- Name: trust_transactions trust_transactions_decision_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trust_transactions
    ADD CONSTRAINT trust_transactions_decision_id_fkey FOREIGN KEY (decision_id) REFERENCES public.trust_decisions(id) ON DELETE RESTRICT;


--
-- Name: utility_readings utility_readings_utility_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.utility_readings
    ADD CONSTRAINT utility_readings_utility_id_fkey FOREIGN KEY (utility_id) REFERENCES public.property_utilities(id) ON DELETE CASCADE;


--
-- Name: vrs_add_ons vrs_add_ons_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vrs_add_ons
    ADD CONSTRAINT vrs_add_ons_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- Name: vrs_automation_events vrs_automation_events_rule_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vrs_automation_events
    ADD CONSTRAINT vrs_automation_events_rule_id_fkey FOREIGN KEY (rule_id) REFERENCES public.vrs_automations(id) ON DELETE SET NULL;


--
-- Name: work_orders work_orders_assigned_vendor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_orders
    ADD CONSTRAINT work_orders_assigned_vendor_id_fkey FOREIGN KEY (assigned_vendor_id) REFERENCES public.vendors(id) ON DELETE SET NULL;


--
-- Name: work_orders work_orders_guest_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_orders
    ADD CONSTRAINT work_orders_guest_id_fkey FOREIGN KEY (guest_id) REFERENCES public.guests(id) ON DELETE SET NULL;


--
-- Name: work_orders work_orders_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_orders
    ADD CONSTRAINT work_orders_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- Name: work_orders work_orders_reported_via_message_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_orders
    ADD CONSTRAINT work_orders_reported_via_message_id_fkey FOREIGN KEY (reported_via_message_id) REFERENCES public.messages(id) ON DELETE SET NULL;


--
-- Name: work_orders work_orders_reservation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_orders
    ADD CONSTRAINT work_orders_reservation_id_fkey FOREIGN KEY (reservation_id) REFERENCES public.reservations(id) ON DELETE SET NULL;


--
-- Name: yield_overrides yield_overrides_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.yield_overrides
    ADD CONSTRAINT yield_overrides_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- Name: yield_simulations yield_simulations_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.yield_simulations
    ADD CONSTRAINT yield_simulations_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict YJeY4MxXMci8nmcQ37m9ixOtGJPKeF13E2Shgxfwwmv045ww2nmoLEJ8YukyunV
