-- CI schema snapshot for fortress-guest-platform
-- Generated: 2026-04-25T12:12:32Z
-- Source:    fortress_db
-- Commit:    13866efa658ffe2950593d1e8a48dec8ca691608
-- Alembic:   d8e3c1f5b9a6,m8f9a1b2c3d4
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

\restrict VUrcdL6h86Va4b8PalMVliVEj9OibDpqKcdRaRctoyg85SNJEnJ3GJKYJj1pYCh

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
-- Name: division_a; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA division_a;


--
-- Name: division_b; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA division_b;


--
-- Name: engineering; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA engineering;


--
-- Name: finance; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA finance;


--
-- Name: hedge_fund; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA hedge_fund;


--
-- Name: intelligence; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA intelligence;


--
-- Name: legal; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA legal;


--
-- Name: legal_cmd; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA legal_cmd;


--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: uuid-ossp; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;


--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--



--
-- Name: update_timestamp(); Type: FUNCTION; Schema: legal_cmd; Owner: -
--

CREATE FUNCTION legal_cmd.update_timestamp() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


--
-- Name: enforce_immutable_line_items(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.enforce_immutable_line_items() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    RAISE EXCEPTION 'FORTRESS PROTOCOL: journal_line_items is append-only. Issue a reversing journal entry via void_entry() instead.';
END;
$$;


--
-- Name: enforce_journal_entry_integrity(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.enforce_journal_entry_integrity() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'FORTRESS PROTOCOL: journal_entries cannot be deleted. Use void_entry() to mark entries as void.';
    END IF;

    IF TG_OP = 'UPDATE' THEN
        IF OLD.entry_date IS DISTINCT FROM NEW.entry_date
           OR OLD.description IS DISTINCT FROM NEW.description
           OR OLD.reference_id IS DISTINCT FROM NEW.reference_id
           OR OLD.reference_type IS DISTINCT FROM NEW.reference_type
           OR OLD.property_id IS DISTINCT FROM NEW.property_id
           OR OLD.posted_by IS DISTINCT FROM NEW.posted_by
           OR OLD.source_system IS DISTINCT FROM NEW.source_system THEN
            RAISE EXCEPTION 'FORTRESS PROTOCOL: Financial columns on journal_entries are immutable. Only void-related fields (is_void, void_reason, voided_at, voided_by) may be updated.';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;


--
-- Name: update_updated_at_column(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


--
-- Name: verify_journal_balance(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.verify_journal_balance() RETURNS trigger
    LANGUAGE plpgsql
    AS $_$
DECLARE
    total_debits    NUMERIC(15, 2);
    total_credits   NUMERIC(15, 2);
BEGIN
    SELECT
        COALESCE(SUM(debit), 0),
        COALESCE(SUM(credit), 0)
    INTO total_debits, total_credits
    FROM journal_line_items
    WHERE journal_entry_id = NEW.journal_entry_id;

    IF total_debits != total_credits THEN
        RAISE EXCEPTION
            '[IRON DOME] REJECTED: Entry #% — Debits ($%) != Credits ($%). Delta: $%',
            NEW.journal_entry_id,
            total_debits,
            total_credits,
            ABS(total_debits - total_credits);
    END IF;

    RETURN NEW;
END;
$_$;


SET default_table_access_method = heap;

--
-- Name: account_mappings; Type: TABLE; Schema: division_a; Owner: -
--

CREATE TABLE division_a.account_mappings (
    id integer NOT NULL,
    vendor_name text NOT NULL,
    plaid_category text DEFAULT ''::text,
    debit_account text NOT NULL,
    credit_account text NOT NULL,
    confidence numeric(4,3) DEFAULT 0.0,
    reasoning text DEFAULT ''::text,
    learned_at timestamp with time zone DEFAULT now(),
    source text DEFAULT 'llm'::text
);


--
-- Name: account_mappings_id_seq; Type: SEQUENCE; Schema: division_a; Owner: -
--

CREATE SEQUENCE division_a.account_mappings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: account_mappings_id_seq; Type: SEQUENCE OWNED BY; Schema: division_a; Owner: -
--

ALTER SEQUENCE division_a.account_mappings_id_seq OWNED BY division_a.account_mappings.id;


--
-- Name: audit_log; Type: TABLE; Schema: division_a; Owner: -
--

CREATE TABLE division_a.audit_log (
    id integer NOT NULL,
    action text NOT NULL,
    agent text DEFAULT 'division_a.agent'::text,
    detail jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: audit_log_id_seq; Type: SEQUENCE; Schema: division_a; Owner: -
--

CREATE SEQUENCE division_a.audit_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_log_id_seq; Type: SEQUENCE OWNED BY; Schema: division_a; Owner: -
--

ALTER SEQUENCE division_a.audit_log_id_seq OWNED BY division_a.audit_log.id;


--
-- Name: general_ledger; Type: TABLE; Schema: division_a; Owner: -
--

CREATE TABLE division_a.general_ledger (
    id integer NOT NULL,
    journal_entry_id text NOT NULL,
    account_code text NOT NULL,
    account_name text NOT NULL,
    debit numeric(14,2) DEFAULT 0.00 NOT NULL,
    credit numeric(14,2) DEFAULT 0.00 NOT NULL,
    memo text DEFAULT ''::text,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT debit_xor_credit CHECK ((((debit > (0)::numeric) AND (credit = (0)::numeric)) OR ((debit = (0)::numeric) AND (credit > (0)::numeric))))
);


--
-- Name: balance_check; Type: VIEW; Schema: division_a; Owner: -
--

CREATE VIEW division_a.balance_check AS
 SELECT sum(debit) AS total_debits,
    sum(credit) AS total_credits,
    (sum(debit) - sum(credit)) AS imbalance,
        CASE
            WHEN (sum(debit) = sum(credit)) THEN 'BALANCED'::text
            ELSE 'IMBALANCED'::text
        END AS status
   FROM division_a.general_ledger;


--
-- Name: chart_of_accounts; Type: TABLE; Schema: division_a; Owner: -
--

CREATE TABLE division_a.chart_of_accounts (
    id integer NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    account_type text NOT NULL,
    parent_code text,
    description text DEFAULT ''::text,
    is_active boolean DEFAULT true,
    qbo_id text,
    qbo_name text,
    normal_balance text DEFAULT 'debit'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT valid_account_type CHECK ((account_type = ANY (ARRAY['asset'::text, 'liability'::text, 'equity'::text, 'revenue'::text, 'expense'::text, 'cogs'::text]))),
    CONSTRAINT valid_normal_balance CHECK ((normal_balance = ANY (ARRAY['debit'::text, 'credit'::text])))
);


--
-- Name: chart_of_accounts_id_seq; Type: SEQUENCE; Schema: division_a; Owner: -
--

CREATE SEQUENCE division_a.chart_of_accounts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: chart_of_accounts_id_seq; Type: SEQUENCE OWNED BY; Schema: division_a; Owner: -
--

ALTER SEQUENCE division_a.chart_of_accounts_id_seq OWNED BY division_a.chart_of_accounts.id;


--
-- Name: general_ledger_id_seq; Type: SEQUENCE; Schema: division_a; Owner: -
--

CREATE SEQUENCE division_a.general_ledger_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: general_ledger_id_seq; Type: SEQUENCE OWNED BY; Schema: division_a; Owner: -
--

ALTER SEQUENCE division_a.general_ledger_id_seq OWNED BY division_a.general_ledger.id;


--
-- Name: journal_entries; Type: TABLE; Schema: division_a; Owner: -
--

CREATE TABLE division_a.journal_entries (
    id integer NOT NULL,
    entry_id text NOT NULL,
    entry_date date NOT NULL,
    description text NOT NULL,
    source_type text DEFAULT 'plaid'::text,
    source_ref text DEFAULT ''::text,
    memo text DEFAULT ''::text,
    is_posted boolean DEFAULT false,
    created_by text DEFAULT 'fortress'::text,
    created_at timestamp with time zone DEFAULT now(),
    posted_at timestamp with time zone
);


--
-- Name: journal_entries_id_seq; Type: SEQUENCE; Schema: division_a; Owner: -
--

CREATE SEQUENCE division_a.journal_entries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: journal_entries_id_seq; Type: SEQUENCE OWNED BY; Schema: division_a; Owner: -
--

ALTER SEQUENCE division_a.journal_entries_id_seq OWNED BY division_a.journal_entries.id;


--
-- Name: predictions; Type: TABLE; Schema: division_a; Owner: -
--

CREATE TABLE division_a.predictions (
    id integer NOT NULL,
    metric_name text NOT NULL,
    predicted_value numeric(14,4),
    actual_value numeric(14,4),
    variance_pct numeric(8,4),
    cycle_id integer,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: predictions_id_seq; Type: SEQUENCE; Schema: division_a; Owner: -
--

CREATE SEQUENCE division_a.predictions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: predictions_id_seq; Type: SEQUENCE OWNED BY; Schema: division_a; Owner: -
--

ALTER SEQUENCE division_a.predictions_id_seq OWNED BY division_a.predictions.id;


--
-- Name: transactions; Type: TABLE; Schema: division_a; Owner: -
--

CREATE TABLE division_a.transactions (
    id integer NOT NULL,
    plaid_txn_id text,
    date date NOT NULL,
    vendor text NOT NULL,
    amount numeric(12,2) NOT NULL,
    category text DEFAULT 'UNCATEGORIZED'::text NOT NULL,
    confidence numeric(4,3) DEFAULT 0.0,
    roi_impact text DEFAULT 'neutral'::text,
    reasoning text,
    method text DEFAULT 'manual'::text,
    account_id text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: transactions_id_seq; Type: SEQUENCE; Schema: division_a; Owner: -
--

CREATE SEQUENCE division_a.transactions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: transactions_id_seq; Type: SEQUENCE OWNED BY; Schema: division_a; Owner: -
--

ALTER SEQUENCE division_a.transactions_id_seq OWNED BY division_a.transactions.id;


--
-- Name: trial_balance; Type: VIEW; Schema: division_a; Owner: -
--

CREATE VIEW division_a.trial_balance AS
 SELECT coa.code,
    coa.name,
    coa.account_type,
    coa.normal_balance,
    COALESCE(sum(gl.debit), (0)::numeric) AS total_debits,
    COALESCE(sum(gl.credit), (0)::numeric) AS total_credits,
    (COALESCE(sum(gl.debit), (0)::numeric) - COALESCE(sum(gl.credit), (0)::numeric)) AS net_balance
   FROM (division_a.chart_of_accounts coa
     LEFT JOIN division_a.general_ledger gl ON ((gl.account_code = coa.code)))
  WHERE (coa.is_active = true)
  GROUP BY coa.code, coa.name, coa.account_type, coa.normal_balance
  ORDER BY coa.code;


--
-- Name: account_mappings; Type: TABLE; Schema: division_b; Owner: -
--

CREATE TABLE division_b.account_mappings (
    id integer NOT NULL,
    vendor_name text NOT NULL,
    plaid_category text DEFAULT ''::text,
    debit_account text NOT NULL,
    credit_account text NOT NULL,
    confidence numeric(4,3) DEFAULT 0.0,
    reasoning text DEFAULT ''::text,
    learned_at timestamp with time zone DEFAULT now(),
    source text DEFAULT 'llm'::text
);


--
-- Name: account_mappings_id_seq; Type: SEQUENCE; Schema: division_b; Owner: -
--

CREATE SEQUENCE division_b.account_mappings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: account_mappings_id_seq; Type: SEQUENCE OWNED BY; Schema: division_b; Owner: -
--

ALTER SEQUENCE division_b.account_mappings_id_seq OWNED BY division_b.account_mappings.id;


--
-- Name: general_ledger; Type: TABLE; Schema: division_b; Owner: -
--

CREATE TABLE division_b.general_ledger (
    id integer NOT NULL,
    journal_entry_id text NOT NULL,
    account_code text NOT NULL,
    account_name text NOT NULL,
    debit numeric(14,2) DEFAULT 0.00 NOT NULL,
    credit numeric(14,2) DEFAULT 0.00 NOT NULL,
    memo text DEFAULT ''::text,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT debit_xor_credit CHECK ((((debit > (0)::numeric) AND (credit = (0)::numeric)) OR ((debit = (0)::numeric) AND (credit > (0)::numeric))))
);


--
-- Name: balance_check; Type: VIEW; Schema: division_b; Owner: -
--

CREATE VIEW division_b.balance_check AS
 SELECT sum(debit) AS total_debits,
    sum(credit) AS total_credits,
    (sum(debit) - sum(credit)) AS imbalance,
        CASE
            WHEN (sum(debit) = sum(credit)) THEN 'BALANCED'::text
            ELSE 'IMBALANCED'::text
        END AS status
   FROM division_b.general_ledger;


--
-- Name: chart_of_accounts; Type: TABLE; Schema: division_b; Owner: -
--

CREATE TABLE division_b.chart_of_accounts (
    id integer NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    account_type text NOT NULL,
    parent_code text,
    description text DEFAULT ''::text,
    is_active boolean DEFAULT true,
    qbo_id text,
    qbo_name text,
    normal_balance text DEFAULT 'debit'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT valid_account_type CHECK ((account_type = ANY (ARRAY['asset'::text, 'liability'::text, 'equity'::text, 'revenue'::text, 'expense'::text, 'cogs'::text]))),
    CONSTRAINT valid_normal_balance CHECK ((normal_balance = ANY (ARRAY['debit'::text, 'credit'::text])))
);


--
-- Name: chart_of_accounts_id_seq; Type: SEQUENCE; Schema: division_b; Owner: -
--

CREATE SEQUENCE division_b.chart_of_accounts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: chart_of_accounts_id_seq; Type: SEQUENCE OWNED BY; Schema: division_b; Owner: -
--

ALTER SEQUENCE division_b.chart_of_accounts_id_seq OWNED BY division_b.chart_of_accounts.id;


--
-- Name: escrow; Type: TABLE; Schema: division_b; Owner: -
--

CREATE TABLE division_b.escrow (
    id integer NOT NULL,
    reservation_id text NOT NULL,
    guest_name text NOT NULL,
    cabin_id text NOT NULL,
    amount numeric(12,2) NOT NULL,
    deposit_date date NOT NULL,
    checkout_date date,
    release_date date,
    status text DEFAULT 'held'::text,
    notes text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: escrow_id_seq; Type: SEQUENCE; Schema: division_b; Owner: -
--

CREATE SEQUENCE division_b.escrow_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: escrow_id_seq; Type: SEQUENCE OWNED BY; Schema: division_b; Owner: -
--

ALTER SEQUENCE division_b.escrow_id_seq OWNED BY division_b.escrow.id;


--
-- Name: general_ledger_id_seq; Type: SEQUENCE; Schema: division_b; Owner: -
--

CREATE SEQUENCE division_b.general_ledger_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: general_ledger_id_seq; Type: SEQUENCE OWNED BY; Schema: division_b; Owner: -
--

ALTER SEQUENCE division_b.general_ledger_id_seq OWNED BY division_b.general_ledger.id;


--
-- Name: journal_entries; Type: TABLE; Schema: division_b; Owner: -
--

CREATE TABLE division_b.journal_entries (
    id integer NOT NULL,
    entry_id text NOT NULL,
    entry_date date NOT NULL,
    description text NOT NULL,
    source_type text DEFAULT 'plaid'::text,
    source_ref text DEFAULT ''::text,
    memo text DEFAULT ''::text,
    is_posted boolean DEFAULT false,
    created_by text DEFAULT 'fortress'::text,
    created_at timestamp with time zone DEFAULT now(),
    posted_at timestamp with time zone
);


--
-- Name: journal_entries_id_seq; Type: SEQUENCE; Schema: division_b; Owner: -
--

CREATE SEQUENCE division_b.journal_entries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: journal_entries_id_seq; Type: SEQUENCE OWNED BY; Schema: division_b; Owner: -
--

ALTER SEQUENCE division_b.journal_entries_id_seq OWNED BY division_b.journal_entries.id;


--
-- Name: predictions; Type: TABLE; Schema: division_b; Owner: -
--

CREATE TABLE division_b.predictions (
    id integer NOT NULL,
    metric_name text NOT NULL,
    predicted_value numeric(14,4),
    actual_value numeric(14,4),
    variance_pct numeric(8,4),
    cycle_id integer,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: predictions_id_seq; Type: SEQUENCE; Schema: division_b; Owner: -
--

CREATE SEQUENCE division_b.predictions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: predictions_id_seq; Type: SEQUENCE OWNED BY; Schema: division_b; Owner: -
--

ALTER SEQUENCE division_b.predictions_id_seq OWNED BY division_b.predictions.id;


--
-- Name: transactions; Type: TABLE; Schema: division_b; Owner: -
--

CREATE TABLE division_b.transactions (
    id integer NOT NULL,
    plaid_txn_id text,
    date date NOT NULL,
    vendor text NOT NULL,
    amount numeric(12,2) NOT NULL,
    category text DEFAULT 'UNCATEGORIZED'::text NOT NULL,
    confidence numeric(4,3) DEFAULT 0.0,
    trust_related boolean DEFAULT false,
    reservation_id text,
    reasoning text,
    method text DEFAULT 'manual'::text,
    account_id text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: transactions_id_seq; Type: SEQUENCE; Schema: division_b; Owner: -
--

CREATE SEQUENCE division_b.transactions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: transactions_id_seq; Type: SEQUENCE OWNED BY; Schema: division_b; Owner: -
--

ALTER SEQUENCE division_b.transactions_id_seq OWNED BY division_b.transactions.id;


--
-- Name: trial_balance; Type: VIEW; Schema: division_b; Owner: -
--

CREATE VIEW division_b.trial_balance AS
 SELECT coa.code,
    coa.name,
    coa.account_type,
    coa.normal_balance,
    COALESCE(sum(gl.debit), (0)::numeric) AS total_debits,
    COALESCE(sum(gl.credit), (0)::numeric) AS total_credits,
    (COALESCE(sum(gl.debit), (0)::numeric) - COALESCE(sum(gl.credit), (0)::numeric)) AS net_balance
   FROM (division_b.chart_of_accounts coa
     LEFT JOIN division_b.general_ledger gl ON ((gl.account_code = coa.code)))
  WHERE (coa.is_active = true)
  GROUP BY coa.code, coa.name, coa.account_type, coa.normal_balance
  ORDER BY coa.code;


--
-- Name: trust_ledger; Type: TABLE; Schema: division_b; Owner: -
--

CREATE TABLE division_b.trust_ledger (
    id integer NOT NULL,
    entry_type text NOT NULL,
    amount numeric(12,2) NOT NULL,
    reference_id text,
    description text,
    running_balance numeric(14,2),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: trust_ledger_id_seq; Type: SEQUENCE; Schema: division_b; Owner: -
--

CREATE SEQUENCE division_b.trust_ledger_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: trust_ledger_id_seq; Type: SEQUENCE OWNED BY; Schema: division_b; Owner: -
--

ALTER SEQUENCE division_b.trust_ledger_id_seq OWNED BY division_b.trust_ledger.id;


--
-- Name: vendor_payouts; Type: TABLE; Schema: division_b; Owner: -
--

CREATE TABLE division_b.vendor_payouts (
    id integer NOT NULL,
    vendor_name text NOT NULL,
    amount numeric(12,2) NOT NULL,
    invoice_number text,
    invoice_date date,
    cabin_id text,
    category text DEFAULT 'MAINTENANCE'::text,
    status text DEFAULT 'pending'::text,
    approved_by text,
    plaid_txn_id text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: vendor_payouts_id_seq; Type: SEQUENCE; Schema: division_b; Owner: -
--

CREATE SEQUENCE division_b.vendor_payouts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vendor_payouts_id_seq; Type: SEQUENCE OWNED BY; Schema: division_b; Owner: -
--

ALTER SEQUENCE division_b.vendor_payouts_id_seq OWNED BY division_b.vendor_payouts.id;


--
-- Name: change_orders; Type: TABLE; Schema: engineering; Owner: -
--

CREATE TABLE engineering.change_orders (
    id integer NOT NULL,
    project_id integer NOT NULL,
    co_number character varying(20) NOT NULL,
    description text NOT NULL,
    reason character varying(50),
    discipline character varying(30),
    cost_impact numeric(12,2),
    schedule_impact_days integer,
    status character varying(20) DEFAULT 'proposed'::character varying NOT NULL,
    submitted_date date,
    approved_date date,
    approved_by character varying(100),
    document_path text,
    notes text,
    ai_json jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: change_orders_id_seq; Type: SEQUENCE; Schema: engineering; Owner: -
--

CREATE SEQUENCE engineering.change_orders_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: change_orders_id_seq; Type: SEQUENCE OWNED BY; Schema: engineering; Owner: -
--

ALTER SEQUENCE engineering.change_orders_id_seq OWNED BY engineering.change_orders.id;


--
-- Name: compliance_log; Type: TABLE; Schema: engineering; Owner: -
--

CREATE TABLE engineering.compliance_log (
    id integer NOT NULL,
    project_id integer,
    property_id integer,
    drawing_id integer,
    issue_type character varying(50) NOT NULL,
    severity character varying(20) DEFAULT 'HIGH'::character varying NOT NULL,
    discipline character varying(30),
    code_reference character varying(100),
    description text NOT NULL,
    recommended_action text,
    status character varying(20) DEFAULT 'open'::character varying NOT NULL,
    resolved_date date,
    resolution_notes text,
    resolved_by character varying(100),
    detected_by character varying(50) DEFAULT 'architect_agent'::character varying,
    ai_json jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: compliance_log_id_seq; Type: SEQUENCE; Schema: engineering; Owner: -
--

CREATE SEQUENCE engineering.compliance_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: compliance_log_id_seq; Type: SEQUENCE OWNED BY; Schema: engineering; Owner: -
--

ALTER SEQUENCE engineering.compliance_log_id_seq OWNED BY engineering.compliance_log.id;


--
-- Name: cost_estimates; Type: TABLE; Schema: engineering; Owner: -
--

CREATE TABLE engineering.cost_estimates (
    id integer NOT NULL,
    project_id integer NOT NULL,
    estimate_type character varying(30) NOT NULL,
    version integer DEFAULT 1,
    architectural_cost numeric(12,2) DEFAULT 0,
    civil_cost numeric(12,2) DEFAULT 0,
    structural_cost numeric(12,2) DEFAULT 0,
    mechanical_cost numeric(12,2) DEFAULT 0,
    electrical_cost numeric(12,2) DEFAULT 0,
    plumbing_cost numeric(12,2) DEFAULT 0,
    fire_protection_cost numeric(12,2) DEFAULT 0,
    general_conditions numeric(12,2) DEFAULT 0,
    contingency numeric(12,2) DEFAULT 0,
    total_estimate numeric(12,2) NOT NULL,
    cost_per_sqft numeric(8,2),
    total_sqft numeric(10,2),
    prepared_by character varying(100),
    estimate_date date,
    document_path text,
    notes text,
    ai_json jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: cost_estimates_id_seq; Type: SEQUENCE; Schema: engineering; Owner: -
--

CREATE SEQUENCE engineering.cost_estimates_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cost_estimates_id_seq; Type: SEQUENCE OWNED BY; Schema: engineering; Owner: -
--

ALTER SEQUENCE engineering.cost_estimates_id_seq OWNED BY engineering.cost_estimates.id;


--
-- Name: drawings; Type: TABLE; Schema: engineering; Owner: -
--

CREATE TABLE engineering.drawings (
    id integer NOT NULL,
    property_id integer,
    project_id integer,
    discipline character varying(30) DEFAULT 'general'::character varying NOT NULL,
    doc_type character varying(50) DEFAULT 'Unknown'::character varying NOT NULL,
    file_path text,
    filename text,
    extension character varying(10),
    file_size bigint,
    sheet_number character varying(20),
    title character varying(200),
    revision character varying(10),
    revision_date date,
    scale character varying(30),
    ocr_text text,
    confidence character varying(20),
    ai_json jsonb,
    phase integer DEFAULT 1,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: drawings_id_seq; Type: SEQUENCE; Schema: engineering; Owner: -
--

CREATE SEQUENCE engineering.drawings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: drawings_id_seq; Type: SEQUENCE OWNED BY; Schema: engineering; Owner: -
--

ALTER SEQUENCE engineering.drawings_id_seq OWNED BY engineering.drawings.id;


--
-- Name: inspections; Type: TABLE; Schema: engineering; Owner: -
--

CREATE TABLE engineering.inspections (
    id integer NOT NULL,
    project_id integer,
    permit_id integer,
    property_id integer,
    inspection_type character varying(50) NOT NULL,
    discipline character varying(30),
    scheduled_date date,
    actual_date date,
    inspector_name character varying(150),
    result character varying(20),
    deficiencies text,
    corrections_required text,
    re_inspection_date date,
    report_path text,
    notes text,
    ai_json jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: inspections_id_seq; Type: SEQUENCE; Schema: engineering; Owner: -
--

CREATE SEQUENCE engineering.inspections_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: inspections_id_seq; Type: SEQUENCE OWNED BY; Schema: engineering; Owner: -
--

ALTER SEQUENCE engineering.inspections_id_seq OWNED BY engineering.inspections.id;


--
-- Name: mep_systems; Type: TABLE; Schema: engineering; Owner: -
--

CREATE TABLE engineering.mep_systems (
    id integer NOT NULL,
    property_id integer NOT NULL,
    property_name character varying(100),
    system_type character varying(50) NOT NULL,
    discipline character varying(30),
    manufacturer character varying(100),
    model_number character varying(100),
    serial_number character varying(100),
    capacity character varying(50),
    fuel_type character varying(30),
    install_date date,
    warranty_expiry date,
    expected_life_years integer,
    condition character varying(20) DEFAULT 'good'::character varying,
    last_service_date date,
    next_service_due date,
    location character varying(100),
    install_cost numeric(10,2),
    replacement_cost numeric(10,2),
    notes text,
    ai_json jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: mep_systems_id_seq; Type: SEQUENCE; Schema: engineering; Owner: -
--

CREATE SEQUENCE engineering.mep_systems_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: mep_systems_id_seq; Type: SEQUENCE OWNED BY; Schema: engineering; Owner: -
--

ALTER SEQUENCE engineering.mep_systems_id_seq OWNED BY engineering.mep_systems.id;


--
-- Name: permits; Type: TABLE; Schema: engineering; Owner: -
--

CREATE TABLE engineering.permits (
    id integer NOT NULL,
    project_id integer,
    property_id integer,
    permit_type character varying(50) NOT NULL,
    permit_number character varying(50),
    jurisdiction character varying(100) DEFAULT 'Fannin County'::character varying,
    issuing_authority character varying(150),
    status character varying(30) DEFAULT 'draft'::character varying NOT NULL,
    application_date date,
    approval_date date,
    expiration_date date,
    renewal_date date,
    application_fee numeric(10,2),
    impact_fee numeric(10,2),
    conditions text,
    special_inspections text[],
    application_doc text,
    approval_doc text,
    notes text,
    ai_json jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: permits_id_seq; Type: SEQUENCE; Schema: engineering; Owner: -
--

CREATE SEQUENCE engineering.permits_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: permits_id_seq; Type: SEQUENCE OWNED BY; Schema: engineering; Owner: -
--

ALTER SEQUENCE engineering.permits_id_seq OWNED BY engineering.permits.id;


--
-- Name: projects; Type: TABLE; Schema: engineering; Owner: -
--

CREATE TABLE engineering.projects (
    id integer NOT NULL,
    project_code character varying(20) NOT NULL,
    name character varying(200) NOT NULL,
    description text,
    property_id integer,
    property_name character varying(100),
    phase character varying(30) DEFAULT 'concept'::character varying NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    project_type character varying(50),
    disciplines text[],
    start_date date,
    target_completion date,
    actual_completion date,
    estimated_cost numeric(12,2),
    actual_cost numeric(12,2),
    contingency_pct numeric(5,2) DEFAULT 10.00,
    architect_of_record character varying(150),
    engineer_of_record character varying(150),
    general_contractor character varying(150),
    project_manager character varying(150),
    jurisdiction character varying(100) DEFAULT 'Fannin County'::character varying,
    permit_number character varying(50),
    notes text,
    ai_json jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: projects_id_seq; Type: SEQUENCE; Schema: engineering; Owner: -
--

CREATE SEQUENCE engineering.projects_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: projects_id_seq; Type: SEQUENCE OWNED BY; Schema: engineering; Owner: -
--

ALTER SEQUENCE engineering.projects_id_seq OWNED BY engineering.projects.id;


--
-- Name: punch_items; Type: TABLE; Schema: engineering; Owner: -
--

CREATE TABLE engineering.punch_items (
    id integer NOT NULL,
    project_id integer NOT NULL,
    inspection_id integer,
    item_number integer NOT NULL,
    description text NOT NULL,
    discipline character varying(30),
    location character varying(100),
    priority character varying(20) DEFAULT 'normal'::character varying,
    assigned_to character varying(100),
    due_date date,
    status character varying(20) DEFAULT 'open'::character varying NOT NULL,
    completed_date date,
    verified_by character varying(100),
    photo_before text,
    photo_after text,
    notes text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: punch_items_id_seq; Type: SEQUENCE; Schema: engineering; Owner: -
--

CREATE SEQUENCE engineering.punch_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: punch_items_id_seq; Type: SEQUENCE OWNED BY; Schema: engineering; Owner: -
--

ALTER SEQUENCE engineering.punch_items_id_seq OWNED BY engineering.punch_items.id;


--
-- Name: rfis; Type: TABLE; Schema: engineering; Owner: -
--

CREATE TABLE engineering.rfis (
    id integer NOT NULL,
    project_id integer NOT NULL,
    rfi_number character varying(20) NOT NULL,
    subject character varying(200) NOT NULL,
    question text NOT NULL,
    discipline character varying(30),
    drawing_reference character varying(50),
    response text,
    responded_by character varying(100),
    response_date date,
    cost_impact numeric(12,2),
    schedule_impact_days integer,
    status character varying(20) DEFAULT 'open'::character varying NOT NULL,
    submitted_date date,
    due_date date,
    submitted_by character varying(100),
    notes text,
    ai_json jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: rfis_id_seq; Type: SEQUENCE; Schema: engineering; Owner: -
--

CREATE SEQUENCE engineering.rfis_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: rfis_id_seq; Type: SEQUENCE OWNED BY; Schema: engineering; Owner: -
--

ALTER SEQUENCE engineering.rfis_id_seq OWNED BY engineering.rfis.id;


--
-- Name: submittals; Type: TABLE; Schema: engineering; Owner: -
--

CREATE TABLE engineering.submittals (
    id integer NOT NULL,
    project_id integer NOT NULL,
    submittal_number character varying(20) NOT NULL,
    description character varying(200) NOT NULL,
    discipline character varying(30),
    spec_section character varying(20),
    status character varying(30) DEFAULT 'pending'::character varying NOT NULL,
    submitted_date date,
    review_date date,
    reviewed_by character varying(100),
    review_comments text,
    document_path text,
    notes text,
    ai_json jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: submittals_id_seq; Type: SEQUENCE; Schema: engineering; Owner: -
--

CREATE SEQUENCE engineering.submittals_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: submittals_id_seq; Type: SEQUENCE OWNED BY; Schema: engineering; Owner: -
--

ALTER SEQUENCE engineering.submittals_id_seq OWNED BY engineering.submittals.id;


--
-- Name: classification_rules; Type: TABLE; Schema: finance; Owner: -
--

CREATE TABLE finance.classification_rules (
    id integer NOT NULL,
    vendor_pattern text NOT NULL,
    assigned_category text NOT NULL,
    reasoning text,
    source_vendor_id integer,
    embedding public.vector(768),
    created_at timestamp with time zone DEFAULT now(),
    created_by text DEFAULT 'CFO-MANUAL'::text
);


--
-- Name: classification_rules_id_seq; Type: SEQUENCE; Schema: finance; Owner: -
--

CREATE SEQUENCE finance.classification_rules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: classification_rules_id_seq; Type: SEQUENCE OWNED BY; Schema: finance; Owner: -
--

ALTER SEQUENCE finance.classification_rules_id_seq OWNED BY finance.classification_rules.id;


--
-- Name: vendor_classifications; Type: TABLE; Schema: finance; Owner: -
--

CREATE TABLE finance.vendor_classifications (
    id integer NOT NULL,
    vendor_pattern text NOT NULL,
    vendor_label text NOT NULL,
    classification text NOT NULL,
    is_revenue boolean DEFAULT false,
    is_expense boolean DEFAULT false,
    titan_notes text,
    classified_at timestamp without time zone DEFAULT now(),
    classified_by text DEFAULT 'TITAN-R1-671B'::text,
    CONSTRAINT vendor_classifications_classification_check CHECK ((classification = ANY (ARRAY['OWNER_PRINCIPAL'::text, 'REAL_BUSINESS'::text, 'CONTRACTOR'::text, 'CROG_INTERNAL'::text, 'FAMILY_INTERNAL'::text, 'FINANCIAL_SERVICE'::text, 'PROFESSIONAL_SERVICE'::text, 'LEGAL_SERVICE'::text, 'INSURANCE'::text, 'OPERATIONAL_EXPENSE'::text, 'SUBSCRIPTION'::text, 'MARKETING'::text, 'TENANT_GUEST'::text, 'PERSONAL_EXPENSE'::text, 'GOVERNMENT'::text, 'LITIGATION_RECOVERY'::text, 'NOISE'::text, 'UNKNOWN'::text])))
);


--
-- Name: vendor_classifications_id_seq; Type: SEQUENCE; Schema: finance; Owner: -
--

CREATE SEQUENCE finance.vendor_classifications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vendor_classifications_id_seq; Type: SEQUENCE OWNED BY; Schema: finance; Owner: -
--

ALTER SEQUENCE finance.vendor_classifications_id_seq OWNED BY finance.vendor_classifications.id;


--
-- Name: active_strategies; Type: TABLE; Schema: hedge_fund; Owner: -
--

CREATE TABLE hedge_fund.active_strategies (
    id integer NOT NULL,
    strategy_name character varying(100) NOT NULL,
    description text,
    allocation_limit numeric(12,2),
    risk_level character varying(20),
    status character varying(20) DEFAULT 'ACTIVE'::character varying,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: active_strategies_id_seq; Type: SEQUENCE; Schema: hedge_fund; Owner: -
--

CREATE SEQUENCE hedge_fund.active_strategies_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: active_strategies_id_seq; Type: SEQUENCE OWNED BY; Schema: hedge_fund; Owner: -
--

ALTER SEQUENCE hedge_fund.active_strategies_id_seq OWNED BY hedge_fund.active_strategies.id;


--
-- Name: extraction_log; Type: TABLE; Schema: hedge_fund; Owner: -
--

CREATE TABLE hedge_fund.extraction_log (
    id integer NOT NULL,
    email_id integer,
    status character varying(20),
    signals_found integer DEFAULT 0,
    model_used character varying(50),
    latency_ms integer,
    error_message text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: extraction_log_id_seq; Type: SEQUENCE; Schema: hedge_fund; Owner: -
--

CREATE SEQUENCE hedge_fund.extraction_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: extraction_log_id_seq; Type: SEQUENCE OWNED BY; Schema: hedge_fund; Owner: -
--

ALTER SEQUENCE hedge_fund.extraction_log_id_seq OWNED BY hedge_fund.extraction_log.id;


--
-- Name: market_signals; Type: TABLE; Schema: hedge_fund; Owner: -
--

CREATE TABLE hedge_fund.market_signals (
    id integer NOT NULL,
    ticker character varying(10) NOT NULL,
    signal_type character varying(50),
    action character varying(20),
    sentiment_score double precision,
    confidence_score integer DEFAULT 0,
    price_target numeric(12,2),
    source_email_id integer,
    source_sender text,
    source_subject text,
    raw_reasoning text,
    model_used character varying(50),
    extracted_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: market_signals_id_seq; Type: SEQUENCE; Schema: hedge_fund; Owner: -
--

CREATE SEQUENCE hedge_fund.market_signals_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: market_signals_id_seq; Type: SEQUENCE OWNED BY; Schema: hedge_fund; Owner: -
--

ALTER SEQUENCE hedge_fund.market_signals_id_seq OWNED BY hedge_fund.market_signals.id;


--
-- Name: watchlist; Type: TABLE; Schema: hedge_fund; Owner: -
--

CREATE TABLE hedge_fund.watchlist (
    id integer NOT NULL,
    ticker character varying(10) NOT NULL,
    sector character varying(50),
    thesis text,
    added_by character varying(50) DEFAULT 'system'::character varying,
    signal_count integer DEFAULT 0,
    last_signal_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: watchlist_id_seq; Type: SEQUENCE; Schema: hedge_fund; Owner: -
--

CREATE SEQUENCE hedge_fund.watchlist_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: watchlist_id_seq; Type: SEQUENCE OWNED BY; Schema: hedge_fund; Owner: -
--

ALTER SEQUENCE hedge_fund.watchlist_id_seq OWNED BY hedge_fund.watchlist.id;


--
-- Name: entities; Type: TABLE; Schema: intelligence; Owner: -
--

CREATE TABLE intelligence.entities (
    id integer NOT NULL,
    entity_type text NOT NULL,
    entity_key text NOT NULL,
    display_name text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb,
    source_table text,
    source_id text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: entities_id_seq; Type: SEQUENCE; Schema: intelligence; Owner: -
--

CREATE SEQUENCE intelligence.entities_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: entities_id_seq; Type: SEQUENCE OWNED BY; Schema: intelligence; Owner: -
--

ALTER SEQUENCE intelligence.entities_id_seq OWNED BY intelligence.entities.id;


--
-- Name: golden_reasoning; Type: TABLE; Schema: intelligence; Owner: -
--

CREATE TABLE intelligence.golden_reasoning (
    id integer NOT NULL,
    topic text NOT NULL,
    entity_key text,
    bad_reasoning text,
    correct_reasoning text NOT NULL,
    correction_type text DEFAULT 'FACTUAL'::text,
    created_by text DEFAULT 'Gary'::text,
    created_at timestamp without time zone DEFAULT now(),
    used_count integer DEFAULT 0,
    CONSTRAINT golden_reasoning_correction_type_check CHECK ((correction_type = ANY (ARRAY['FACTUAL'::text, 'CLASSIFICATION'::text, 'MISSING_LINK'::text, 'LOGIC_ERROR'::text])))
);


--
-- Name: golden_reasoning_id_seq; Type: SEQUENCE; Schema: intelligence; Owner: -
--

CREATE SEQUENCE intelligence.golden_reasoning_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: golden_reasoning_id_seq; Type: SEQUENCE OWNED BY; Schema: intelligence; Owner: -
--

ALTER SEQUENCE intelligence.golden_reasoning_id_seq OWNED BY intelligence.golden_reasoning.id;


--
-- Name: relationships; Type: TABLE; Schema: intelligence; Owner: -
--

CREATE TABLE intelligence.relationships (
    id integer NOT NULL,
    from_entity_id integer NOT NULL,
    to_entity_id integer NOT NULL,
    relationship_type text NOT NULL,
    confidence numeric(3,2) DEFAULT 1.00,
    metadata jsonb DEFAULT '{}'::jsonb,
    source text DEFAULT 'SYSTEM'::text,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: relationships_id_seq; Type: SEQUENCE; Schema: intelligence; Owner: -
--

CREATE SEQUENCE intelligence.relationships_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: relationships_id_seq; Type: SEQUENCE OWNED BY; Schema: intelligence; Owner: -
--

ALTER SEQUENCE intelligence.relationships_id_seq OWNED BY intelligence.relationships.id;


--
-- Name: titan_traces; Type: TABLE; Schema: intelligence; Owner: -
--

CREATE TABLE intelligence.titan_traces (
    id integer NOT NULL,
    trace_id uuid DEFAULT gen_random_uuid(),
    session_type text NOT NULL,
    defcon_mode text DEFAULT 'TITAN'::text,
    system_prompt text,
    user_context text,
    context_chars integer,
    thinking_trace text,
    response text,
    thinking_tokens integer,
    response_tokens integer,
    latency_ms integer,
    model text,
    corrections jsonb DEFAULT '[]'::jsonb,
    score integer,
    score_comment text,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: titan_traces_id_seq; Type: SEQUENCE; Schema: intelligence; Owner: -
--

CREATE SEQUENCE intelligence.titan_traces_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: titan_traces_id_seq; Type: SEQUENCE OWNED BY; Schema: intelligence; Owner: -
--

ALTER SEQUENCE intelligence.titan_traces_id_seq OWNED BY intelligence.titan_traces.id;


--
-- Name: case_actions; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.case_actions (
    id integer NOT NULL,
    case_id integer,
    action_type text NOT NULL,
    action_date timestamp with time zone DEFAULT now(),
    description text NOT NULL,
    status text DEFAULT 'pending'::text,
    tracking_number text,
    attachments text[],
    notes text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: case_actions_id_seq; Type: SEQUENCE; Schema: legal; Owner: -
--

CREATE SEQUENCE legal.case_actions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: case_actions_id_seq; Type: SEQUENCE OWNED BY; Schema: legal; Owner: -
--

ALTER SEQUENCE legal.case_actions_id_seq OWNED BY legal.case_actions.id;


--
-- Name: case_evidence; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.case_evidence (
    id integer NOT NULL,
    case_id integer,
    evidence_type text NOT NULL,
    email_id integer,
    file_path text,
    description text NOT NULL,
    relevance text,
    discovered_at timestamp with time zone DEFAULT now(),
    is_critical boolean DEFAULT false
);


--
-- Name: case_evidence_id_seq; Type: SEQUENCE; Schema: legal; Owner: -
--

CREATE SEQUENCE legal.case_evidence_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: case_evidence_id_seq; Type: SEQUENCE OWNED BY; Schema: legal; Owner: -
--

ALTER SEQUENCE legal.case_evidence_id_seq OWNED BY legal.case_evidence.id;


--
-- Name: case_precedents; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.case_precedents (
    id integer NOT NULL,
    case_slug text NOT NULL,
    citation text NOT NULL,
    url text,
    relevance_score integer NOT NULL,
    justification text NOT NULL,
    extracted_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT case_precedents_relevance_score_check CHECK (((relevance_score >= 0) AND (relevance_score <= 100)))
);


--
-- Name: case_precedents_id_seq; Type: SEQUENCE; Schema: legal; Owner: -
--

CREATE SEQUENCE legal.case_precedents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: case_precedents_id_seq; Type: SEQUENCE OWNED BY; Schema: legal; Owner: -
--

ALTER SEQUENCE legal.case_precedents_id_seq OWNED BY legal.case_precedents.id;


--
-- Name: case_watchdog; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.case_watchdog (
    id integer NOT NULL,
    case_id integer,
    search_type text NOT NULL,
    search_term text NOT NULL,
    priority text DEFAULT 'P2'::text,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: case_watchdog_id_seq; Type: SEQUENCE; Schema: legal; Owner: -
--

CREATE SEQUENCE legal.case_watchdog_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: case_watchdog_id_seq; Type: SEQUENCE OWNED BY; Schema: legal; Owner: -
--

ALTER SEQUENCE legal.case_watchdog_id_seq OWNED BY legal.case_watchdog.id;


--
-- Name: cases; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.cases (
    id integer NOT NULL,
    case_slug text NOT NULL,
    case_number text NOT NULL,
    case_name text NOT NULL,
    court text,
    judge text,
    case_type text DEFAULT 'bankruptcy'::text,
    our_role text DEFAULT 'creditor'::text,
    status text DEFAULT 'active'::text,
    critical_date date,
    critical_note text,
    plan_admin text,
    plan_admin_email text,
    plan_admin_address text,
    fiduciary text,
    opposing_counsel text,
    our_claim_basis text,
    petition_date date,
    notes text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    risk_score integer,
    extraction_status text DEFAULT 'none'::text,
    extracted_entities jsonb DEFAULT '{}'::jsonb,
    active_brief text,
    active_consensus jsonb,
    nas_layout jsonb,
    CONSTRAINT cases_risk_score_check CHECK (((risk_score >= 1) AND (risk_score <= 5)))
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
-- Name: correspondence; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.correspondence (
    id integer NOT NULL,
    case_id integer,
    direction text DEFAULT 'outbound'::text NOT NULL,
    comm_type text NOT NULL,
    recipient text,
    recipient_email text,
    subject text NOT NULL,
    body text,
    status text DEFAULT 'draft'::text,
    gmail_draft_id text,
    tracking_number text,
    file_path text,
    approved_by text,
    approved_at timestamp with time zone,
    sent_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    risk_score integer,
    extraction_status text DEFAULT 'none'::text,
    extracted_entities jsonb DEFAULT '{}'::jsonb,
    CONSTRAINT correspondence_risk_score_check CHECK (((risk_score >= 1) AND (risk_score <= 5)))
);


--
-- Name: correspondence_id_seq; Type: SEQUENCE; Schema: legal; Owner: -
--

CREATE SEQUENCE legal.correspondence_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: correspondence_id_seq; Type: SEQUENCE OWNED BY; Schema: legal; Owner: -
--

ALTER SEQUENCE legal.correspondence_id_seq OWNED BY legal.correspondence.id;


--
-- Name: deadlines; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.deadlines (
    id integer NOT NULL,
    case_id integer,
    deadline_type text NOT NULL,
    description text NOT NULL,
    due_date date NOT NULL,
    alert_days_before integer DEFAULT 7,
    status text DEFAULT 'pending'::text,
    extended_to date,
    extension_reason text,
    created_at timestamp with time zone DEFAULT now(),
    source_document text,
    auto_extracted boolean DEFAULT false,
    review_status character varying(20) DEFAULT 'pending_review'::character varying,
    content_hash character varying(32)
);


--
-- Name: deadlines_id_seq; Type: SEQUENCE; Schema: legal; Owner: -
--

CREATE SEQUENCE legal.deadlines_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: deadlines_id_seq; Type: SEQUENCE OWNED BY; Schema: legal; Owner: -
--

ALTER SEQUENCE legal.deadlines_id_seq OWNED BY legal.deadlines.id;


--
-- Name: email_intake_queue; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.email_intake_queue (
    id integer NOT NULL,
    message_uid text NOT NULL,
    sender_email text NOT NULL,
    sender_name text,
    subject text,
    body_text text,
    case_slug text,
    triage_result jsonb,
    intake_status text DEFAULT 'pending'::text NOT NULL,
    attachment_count integer DEFAULT 0,
    correspondence_id integer,
    received_at timestamp with time zone DEFAULT now() NOT NULL,
    processed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: email_intake_queue_id_seq; Type: SEQUENCE; Schema: legal; Owner: -
--

CREATE SEQUENCE legal.email_intake_queue_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: email_intake_queue_id_seq; Type: SEQUENCE OWNED BY; Schema: legal; Owner: -
--

ALTER SEQUENCE legal.email_intake_queue_id_seq OWNED BY legal.email_intake_queue.id;


--
-- Name: expense_intake; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.expense_intake (
    id integer NOT NULL,
    case_slug text,
    vendor text NOT NULL,
    amount numeric(15,2) DEFAULT 0 NOT NULL,
    description text,
    rag_category text,
    rag_reasoning text,
    audit_trail jsonb DEFAULT '[]'::jsonb,
    source_system text DEFAULT 'triage_router'::text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: expense_intake_id_seq; Type: SEQUENCE; Schema: legal; Owner: -
--

CREATE SEQUENCE legal.expense_intake_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: expense_intake_id_seq; Type: SEQUENCE OWNED BY; Schema: legal; Owner: -
--

ALTER SEQUENCE legal.expense_intake_id_seq OWNED BY legal.expense_intake.id;


--
-- Name: filings; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.filings (
    id integer NOT NULL,
    case_id integer,
    filing_type text NOT NULL,
    title text NOT NULL,
    filed_date date,
    filed_by text,
    filed_with text,
    filing_location text,
    status text DEFAULT 'filed'::text,
    served_on text,
    served_date date,
    served_method text,
    original_path text,
    stamped_path text,
    notes text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: filings_id_seq; Type: SEQUENCE; Schema: legal; Owner: -
--

CREATE SEQUENCE legal.filings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: filings_id_seq; Type: SEQUENCE OWNED BY; Schema: legal; Owner: -
--

ALTER SEQUENCE legal.filings_id_seq OWNED BY legal.filings.id;


--
-- Name: ingest_runs; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.ingest_runs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    case_slug text NOT NULL,
    script_name text NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    ended_at timestamp with time zone,
    args jsonb DEFAULT '{}'::jsonb NOT NULL,
    status text DEFAULT 'running'::text NOT NULL,
    manifest_path text,
    total_files integer,
    processed integer,
    errored integer,
    skipped integer,
    error_summary text,
    host text,
    pid integer,
    runtime_seconds numeric(12,3),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ingest_runs_status_check CHECK ((status = ANY (ARRAY['running'::text, 'complete'::text, 'error'::text, 'interrupted'::text])))
);


--
-- Name: timeline_events; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.timeline_events (
    id integer NOT NULL,
    case_slug text NOT NULL,
    event_date date DEFAULT CURRENT_DATE NOT NULL,
    description text,
    source_evidence_id integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: timeline_events_id_seq; Type: SEQUENCE; Schema: legal; Owner: -
--

CREATE SEQUENCE legal.timeline_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: timeline_events_id_seq; Type: SEQUENCE OWNED BY; Schema: legal; Owner: -
--

ALTER SEQUENCE legal.timeline_events_id_seq OWNED BY legal.timeline_events.id;


--
-- Name: uploads; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.uploads (
    id integer NOT NULL,
    case_id integer,
    filename text NOT NULL,
    original_name text NOT NULL,
    content_type text DEFAULT 'application/pdf'::text,
    file_size integer,
    nas_path text NOT NULL,
    upload_type text DEFAULT 'general'::text,
    description text,
    filing_id integer,
    uploaded_by text DEFAULT 'admin'::text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: uploads_id_seq; Type: SEQUENCE; Schema: legal; Owner: -
--

CREATE SEQUENCE legal.uploads_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: uploads_id_seq; Type: SEQUENCE OWNED BY; Schema: legal; Owner: -
--

ALTER SEQUENCE legal.uploads_id_seq OWNED BY legal.uploads.id;


--
-- Name: vault_documents; Type: TABLE; Schema: legal; Owner: -
--

CREATE TABLE legal.vault_documents (
    id uuid NOT NULL,
    case_slug text NOT NULL,
    file_name text NOT NULL,
    nfs_path text NOT NULL,
    mime_type text NOT NULL,
    file_hash text NOT NULL,
    file_size_bytes bigint NOT NULL,
    processing_status text DEFAULT 'pending'::text NOT NULL,
    chunk_count integer,
    error_detail text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT chk_vault_documents_status CHECK ((processing_status = ANY (ARRAY['pending'::text, 'processing'::text, 'vectorizing'::text, 'complete'::text, 'completed'::text, 'ocr_failed'::text, 'error'::text, 'failed'::text, 'locked_privileged'::text])))
);


--
-- Name: attorney_scoring; Type: TABLE; Schema: legal_cmd; Owner: -
--

CREATE TABLE legal_cmd.attorney_scoring (
    id integer NOT NULL,
    attorney_id uuid,
    sota_match_score integer,
    eckles_competency boolean DEFAULT false,
    commercial_litigation_focus boolean DEFAULT false,
    fannin_jurisdiction_match boolean DEFAULT false,
    ai_rationale text,
    scored_by_model text,
    scored_at timestamp without time zone DEFAULT now(),
    CONSTRAINT attorney_scoring_sota_match_score_check CHECK (((sota_match_score >= 0) AND (sota_match_score <= 100)))
);


--
-- Name: attorney_scoring_id_seq; Type: SEQUENCE; Schema: legal_cmd; Owner: -
--

CREATE SEQUENCE legal_cmd.attorney_scoring_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: attorney_scoring_id_seq; Type: SEQUENCE OWNED BY; Schema: legal_cmd; Owner: -
--

ALTER SEQUENCE legal_cmd.attorney_scoring_id_seq OWNED BY legal_cmd.attorney_scoring.id;


--
-- Name: attorneys; Type: TABLE; Schema: legal_cmd; Owner: -
--

CREATE TABLE legal_cmd.attorneys (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    first_name text NOT NULL,
    last_name text NOT NULL,
    firm_name text,
    specialty text,
    email text,
    phone text,
    address text,
    website text,
    bar_number text,
    bar_state text,
    hourly_rate numeric(10,2),
    retainer_amount numeric(10,2),
    retainer_status text DEFAULT 'none'::text,
    engagement_date date,
    status text DEFAULT 'active'::text,
    rating integer,
    notes text,
    tags text[],
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    case_id integer,
    source text,
    source_url text,
    ai_score numeric(3,1),
    ai_score_reasoning text,
    practice_areas text[],
    jurisdiction text[],
    admission_date date,
    outreach_status text DEFAULT 'prospect'::text,
    last_contacted_at timestamp with time zone,
    firm_size character varying(50),
    CONSTRAINT attorneys_rating_check CHECK (((rating >= 1) AND (rating <= 5)))
);


--
-- Name: deliberation_events; Type: TABLE; Schema: legal_cmd; Owner: -
--

CREATE TABLE legal_cmd.deliberation_events (
    event_id uuid DEFAULT gen_random_uuid() NOT NULL,
    case_slug character varying(255) NOT NULL,
    case_number character varying(255),
    "timestamp" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    trigger_type character varying(50) NOT NULL,
    qdrant_vector_ids text[],
    context_chunks text[],
    user_prompt text NOT NULL,
    moe_roster_snapshot jsonb NOT NULL,
    seat_opinions jsonb NOT NULL,
    counsel_results jsonb NOT NULL,
    consensus_signal character varying(50),
    consensus_conviction numeric(4,3),
    execution_time_ms integer,
    sha256_signature character varying(64) NOT NULL
);


--
-- Name: documents; Type: TABLE; Schema: legal_cmd; Owner: -
--

CREATE TABLE legal_cmd.documents (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    matter_id uuid,
    title text NOT NULL,
    doc_type text,
    file_path text,
    file_url text,
    description text,
    uploaded_by text DEFAULT 'owner'::text,
    tags text[],
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: matters; Type: TABLE; Schema: legal_cmd; Owner: -
--

CREATE TABLE legal_cmd.matters (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    title text NOT NULL,
    reference_code text,
    category text NOT NULL,
    status text DEFAULT 'open'::text,
    priority text DEFAULT 'normal'::text,
    description text,
    attorney_id uuid,
    opposing_party text,
    opposing_counsel text,
    amount_at_stake numeric(12,2),
    outcome text,
    outcome_date date,
    next_action text,
    next_action_date date,
    tags text[],
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: meetings; Type: TABLE; Schema: legal_cmd; Owner: -
--

CREATE TABLE legal_cmd.meetings (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    matter_id uuid,
    attorney_id uuid,
    title text NOT NULL,
    meeting_type text DEFAULT 'in_person'::text,
    meeting_date timestamp with time zone NOT NULL,
    duration_minutes integer,
    location text,
    attendees text,
    summary text,
    action_items text,
    key_decisions text,
    documents_discussed text,
    billable boolean DEFAULT false,
    cost numeric(10,2),
    follow_up_date date,
    follow_up_notes text,
    tags text[],
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: timeline; Type: TABLE; Schema: legal_cmd; Owner: -
--

CREATE TABLE legal_cmd.timeline (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    matter_id uuid NOT NULL,
    entry_type text NOT NULL,
    title text NOT NULL,
    body text,
    entered_by text DEFAULT 'owner'::text,
    importance text DEFAULT 'normal'::text,
    related_meeting_id uuid,
    related_attorney_id uuid,
    document_ref text,
    tags text[],
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: ab_test_observations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ab_test_observations (
    id integer NOT NULL,
    test_id integer,
    variant text NOT NULL,
    metric_value numeric(15,4),
    context jsonb,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: ab_test_observations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ab_test_observations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ab_test_observations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ab_test_observations_id_seq OWNED BY public.ab_test_observations.id;


--
-- Name: ab_tests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ab_tests (
    id integer NOT NULL,
    test_name text NOT NULL,
    agent_id text NOT NULL,
    variant_a text NOT NULL,
    variant_b text NOT NULL,
    metric_name text NOT NULL,
    status text DEFAULT 'active'::text,
    winner text,
    created_at timestamp without time zone DEFAULT now(),
    concluded_at timestamp without time zone
);


--
-- Name: ab_tests_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ab_tests_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ab_tests_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ab_tests_id_seq OWNED BY public.ab_tests.id;


--
-- Name: accounts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.accounts (
    id integer NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    account_type text NOT NULL,
    sub_type text,
    normal_balance text NOT NULL,
    parent_id integer,
    property_id text,
    is_active boolean DEFAULT true,
    description text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT accounts_account_type_check CHECK ((account_type = ANY (ARRAY['Asset'::text, 'Liability'::text, 'Equity'::text, 'Revenue'::text, 'Expense'::text]))),
    CONSTRAINT accounts_normal_balance_check CHECK ((normal_balance = ANY (ARRAY['debit'::text, 'credit'::text])))
);


--
-- Name: accounts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.accounts_id_seq
    AS integer
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
-- Name: active_learning_queue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.active_learning_queue (
    id integer NOT NULL,
    judgment_id integer,
    agent_id text NOT NULL,
    metric_name text NOT NULL,
    predicted_value numeric(15,4),
    actual_value numeric(15,4),
    variance_pct numeric(8,4),
    context jsonb,
    status text DEFAULT 'pending'::text,
    reviewer text,
    review_result text,
    review_notes text,
    created_at timestamp without time zone DEFAULT now(),
    reviewed_at timestamp without time zone
);


--
-- Name: active_learning_queue_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.active_learning_queue_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: active_learning_queue_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.active_learning_queue_id_seq OWNED BY public.active_learning_queue.id;


--
-- Name: agent_response_queue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_response_queue (
    id bigint NOT NULL,
    inbound_message_id bigint,
    phone_number character varying(20) NOT NULL,
    guest_name character varying(255),
    cabin_name character varying(100),
    reservation_id character varying(100),
    guest_message text NOT NULL,
    intent character varying(50),
    intent_confidence numeric(4,3),
    sentiment character varying(20),
    urgency_level integer DEFAULT 1,
    escalation_required boolean DEFAULT false,
    escalation_reason text,
    ai_draft text NOT NULL,
    ai_model character varying(100),
    ai_duration_ms integer,
    knowledge_sources jsonb,
    confidence_score numeric(4,3),
    status character varying(20) DEFAULT 'pending_review'::character varying NOT NULL,
    reviewed_by character varying(100),
    reviewed_at timestamp without time zone,
    edited_draft text,
    review_notes text,
    sent_at timestamp without time zone,
    sent_via character varying(20),
    outbound_message_id bigint,
    delivery_status character varying(20),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    expires_at timestamp without time zone,
    quality_grade integer,
    edit_distance_pct numeric(5,2),
    grade_notes text,
    guest_tier character varying(20) DEFAULT 'new'::character varying,
    converted_at timestamp with time zone,
    revenue_generated numeric(10,2) DEFAULT 0.00,
    CONSTRAINT agent_response_queue_quality_grade_check CHECK (((quality_grade >= 1) AND (quality_grade <= 5)))
);


--
-- Name: agent_grade_summary; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.agent_grade_summary AS
 SELECT intent,
    ai_model,
    count(*) AS total,
    count(*) FILTER (WHERE (quality_grade IS NOT NULL)) AS graded,
    round(avg(quality_grade), 2) AS avg_grade,
    round(avg(edit_distance_pct), 1) AS avg_edit_pct,
    count(*) FILTER (WHERE ((status)::text = 'approved'::text)) AS approved_as_is,
    count(*) FILTER (WHERE ((status)::text = 'edited'::text)) AS needed_edit,
    count(*) FILTER (WHERE ((status)::text = 'rejected'::text)) AS rejected,
    round(avg(ai_duration_ms), 0) AS avg_duration_ms
   FROM public.agent_response_queue
  GROUP BY intent, ai_model
  ORDER BY (count(*)) DESC;


--
-- Name: agent_learning_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_learning_log (
    id bigint NOT NULL,
    queue_id bigint,
    pattern_type character varying(50) NOT NULL,
    intent character varying(50),
    cabin_name character varying(100),
    ai_draft text,
    human_edit text,
    correction_summary text,
    quality_grade integer,
    edit_distance_pct numeric(5,2),
    learned_at timestamp without time zone DEFAULT now()
);


--
-- Name: agent_learning_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agent_learning_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agent_learning_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agent_learning_log_id_seq OWNED BY public.agent_learning_log.id;


--
-- Name: agent_memory; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_memory (
    id bigint NOT NULL,
    request_id uuid NOT NULL,
    model character varying(128) NOT NULL,
    reasoning_block text,
    outcome_tags jsonb DEFAULT '[]'::jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    retained_until timestamp with time zone
);


--
-- Name: agent_memory_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agent_memory_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agent_memory_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agent_memory_id_seq OWNED BY public.agent_memory.id;


--
-- Name: agent_performance_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_performance_log (
    id bigint NOT NULL,
    date date DEFAULT CURRENT_DATE NOT NULL,
    messages_received integer DEFAULT 0,
    drafts_generated integer DEFAULT 0,
    drafts_approved integer DEFAULT 0,
    drafts_edited integer DEFAULT 0,
    drafts_rejected integer DEFAULT 0,
    auto_sent integer DEFAULT 0,
    avg_confidence numeric(4,3),
    avg_response_time_ms integer,
    escalation_count integer DEFAULT 0,
    intent_breakdown jsonb,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: agent_performance_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agent_performance_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agent_performance_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agent_performance_log_id_seq OWNED BY public.agent_performance_log.id;


--
-- Name: agent_response_queue_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agent_response_queue_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agent_response_queue_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agent_response_queue_id_seq OWNED BY public.agent_response_queue.id;


--
-- Name: agent_telemetry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_telemetry (
    id bigint NOT NULL,
    request_id uuid NOT NULL,
    prompt_hash character varying(64),
    model character varying(128) NOT NULL,
    route character varying(256),
    latency_ms integer,
    retries smallint DEFAULT '0'::smallint NOT NULL,
    error_class character varying(256),
    user_feedback_signal character varying(32),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    retained_until timestamp with time zone
);


--
-- Name: agent_telemetry_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agent_telemetry_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agent_telemetry_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agent_telemetry_id_seq OWNED BY public.agent_telemetry.id;


--
-- Name: ai_training_labels; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_training_labels (
    id bigint NOT NULL,
    message_id bigint,
    labeled_intent character varying(50) NOT NULL,
    labeled_sentiment character varying(20),
    labeled_urgency integer,
    requires_human boolean,
    response_appropriateness integer,
    response_accuracy integer,
    response_tone integer,
    labeled_by character varying(100) NOT NULL,
    labeled_at timestamp without time zone DEFAULT now(),
    labeling_confidence integer,
    notes text,
    used_in_training_run character varying(100),
    training_epoch integer,
    CONSTRAINT valid_accuracy CHECK ((((response_accuracy >= 1) AND (response_accuracy <= 5)) OR (response_accuracy IS NULL))),
    CONSTRAINT valid_appropriateness CHECK ((((response_appropriateness >= 1) AND (response_appropriateness <= 5)) OR (response_appropriateness IS NULL)))
);


--
-- Name: message_archive; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.message_archive (
    id bigint NOT NULL,
    source character varying(50) NOT NULL,
    external_id character varying(255),
    provider_account character varying(100),
    phone_number character varying(20),
    guest_name character varying(255),
    message_body text NOT NULL,
    direction character varying(10) NOT NULL,
    media_url text[],
    sent_at timestamp without time zone,
    received_at timestamp without time zone,
    delivered_at timestamp without time zone,
    read_at timestamp without time zone,
    failed_at timestamp without time zone,
    property_id integer,
    cabin_name character varying(100),
    reservation_id character varying(100),
    reservation_checkin date,
    reservation_checkout date,
    intent character varying(50),
    intent_confidence numeric(4,3),
    sub_intent character varying(50),
    sentiment character varying(20),
    urgency_level integer,
    contains_question boolean DEFAULT false,
    requires_human boolean DEFAULT false,
    response_generated_by character varying(50),
    response_time_seconds integer,
    ai_model_used character varying(100),
    response_quality_score integer,
    resolution_status character varying(20),
    used_for_training boolean DEFAULT false,
    training_label character varying(50),
    training_split character varying(10),
    human_reviewed boolean DEFAULT false,
    human_reviewer character varying(100),
    review_notes text,
    approved_for_fine_tuning boolean DEFAULT false,
    status character varying(50),
    error_code character varying(50),
    error_message text,
    num_segments integer DEFAULT 1,
    cost_usd numeric(10,6),
    provider_cost_usd numeric(10,6),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    extracted_at timestamp without time zone,
    extraction_method character varying(50),
    channel character varying(20) DEFAULT 'sms'::character varying,
    sender_email text,
    CONSTRAINT valid_direction CHECK (((direction)::text = ANY ((ARRAY['inbound'::character varying, 'outbound'::character varying])::text[]))),
    CONSTRAINT valid_quality CHECK ((((response_quality_score >= 1) AND (response_quality_score <= 5)) OR (response_quality_score IS NULL))),
    CONSTRAINT valid_sentiment CHECK ((((sentiment)::text = ANY ((ARRAY['positive'::character varying, 'neutral'::character varying, 'negative'::character varying, 'urgent'::character varying])::text[])) OR (sentiment IS NULL))),
    CONSTRAINT valid_urgency CHECK ((((urgency_level >= 1) AND (urgency_level <= 5)) OR (urgency_level IS NULL)))
);


--
-- Name: ai_training_dataset; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.ai_training_dataset AS
 SELECT ma.id,
    ma.message_body AS input_text,
    ma.intent AS intent_label,
    ma.sentiment AS sentiment_label,
    ma.direction,
    atl.labeled_intent,
    atl.labeled_sentiment,
    atl.response_appropriateness,
    ma.phone_number,
    ma.property_id,
    ma.sent_at
   FROM (public.message_archive ma
     LEFT JOIN public.ai_training_labels atl ON ((ma.id = atl.message_id)))
  WHERE ((ma.used_for_training = true) AND (ma.human_reviewed = true));


--
-- Name: ai_training_labels_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ai_training_labels_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ai_training_labels_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ai_training_labels_id_seq OWNED BY public.ai_training_labels.id;


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: anomaly_flags; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.anomaly_flags (
    id integer NOT NULL,
    journal_entry_id integer NOT NULL,
    account_id integer,
    flag_type text NOT NULL,
    severity text NOT NULL,
    deviation_pct numeric(8,2),
    expected_amount numeric(15,2),
    actual_amount numeric(15,2),
    ai_explanation text,
    reviewed boolean DEFAULT false,
    reviewed_by text,
    reviewed_at timestamp without time zone,
    review_notes text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT anomaly_flags_flag_type_check CHECK ((flag_type = ANY (ARRAY['amount_deviation'::text, 'unusual_category'::text, 'duplicate_suspect'::text, 'missing_reference'::text, 'trust_imbalance'::text, 'manual_review'::text]))),
    CONSTRAINT anomaly_flags_severity_check CHECK ((severity = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text, 'critical'::text])))
);


--
-- Name: anomaly_flags_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.anomaly_flags_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: anomaly_flags_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.anomaly_flags_id_seq OWNED BY public.anomaly_flags.id;


--
-- Name: api_key_vault; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.api_key_vault (
    id integer NOT NULL,
    key_name character varying(100) NOT NULL,
    encrypted_value text NOT NULL,
    label character varying(100),
    description text,
    category character varying(50) DEFAULT 'General'::character varying,
    last_rotated timestamp with time zone DEFAULT now(),
    created_at timestamp with time zone DEFAULT now(),
    updated_by character varying(50)
);


--
-- Name: api_key_vault_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.api_key_vault_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: api_key_vault_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.api_key_vault_id_seq OWNED BY public.api_key_vault.id;


--
-- Name: asset_docs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.asset_docs (
    id integer NOT NULL,
    property_id integer,
    property_name text,
    doc_type character varying(50),
    file_path text,
    filename text,
    extension text,
    file_size bigint,
    ocr_text text,
    recording_date date,
    book_page character varying(50),
    grantor text,
    grantee text,
    parcel_id character varying(50),
    confidence text,
    ai_json text,
    phase integer DEFAULT 1,
    last_updated timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: asset_docs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.asset_docs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: asset_docs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.asset_docs_id_seq OWNED BY public.asset_docs.id;


--
-- Name: conversation_threads; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.conversation_threads (
    id bigint NOT NULL,
    phone_number character varying(20) NOT NULL,
    property_id integer,
    thread_hash character varying(64),
    started_at timestamp without time zone NOT NULL,
    last_message_at timestamp without time zone NOT NULL,
    message_count integer DEFAULT 0,
    inbound_count integer DEFAULT 0,
    outbound_count integer DEFAULT 0,
    primary_intent character varying(50),
    status character varying(20),
    resolution_time_seconds integer,
    handled_by_ai boolean DEFAULT false,
    ai_success boolean,
    escalated_to_human boolean DEFAULT false,
    escalation_reason text,
    guest_satisfaction_score integer,
    guest_feedback text,
    reservation_id character varying(100),
    cabin_name character varying(100),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    CONSTRAINT valid_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'resolved'::character varying, 'escalated'::character varying, 'abandoned'::character varying])::text[])))
);


--
-- Name: conversation_threads_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.conversation_threads_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: conversation_threads_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.conversation_threads_id_seq OWNED BY public.conversation_threads.id;


--
-- Name: council_votes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.council_votes (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    event text NOT NULL,
    context text,
    model_used character varying(100) DEFAULT 'qwen2.5:7b'::character varying NOT NULL,
    consensus_signal character varying(20) NOT NULL,
    consensus_conviction double precision NOT NULL,
    agreement_rate double precision NOT NULL,
    bullish_count integer DEFAULT 0 NOT NULL,
    bearish_count integer DEFAULT 0 NOT NULL,
    neutral_count integer DEFAULT 0 NOT NULL,
    total_voters integer DEFAULT 9 NOT NULL,
    opinions jsonb DEFAULT '[]'::jsonb NOT NULL,
    signal_breakdown jsonb DEFAULT '{}'::jsonb NOT NULL,
    mode character varying(50),
    elapsed_seconds double precision,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    resolved_at timestamp with time zone,
    actual_outcome character varying(20),
    resolution_notes text
);


--
-- Name: message_analytics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.message_analytics (
    id bigint NOT NULL,
    date date NOT NULL,
    hour integer,
    property_id integer,
    source character varying(50),
    total_messages integer DEFAULT 0,
    inbound_messages integer DEFAULT 0,
    outbound_messages integer DEFAULT 0,
    ai_handled_count integer DEFAULT 0,
    human_handled_count integer DEFAULT 0,
    escalation_count integer DEFAULT 0,
    ai_success_rate numeric(5,4),
    avg_response_time_seconds integer,
    median_response_time_seconds integer,
    p95_response_time_seconds integer,
    intent_distribution jsonb,
    positive_messages integer DEFAULT 0,
    neutral_messages integer DEFAULT 0,
    negative_messages integer DEFAULT 0,
    urgent_messages integer DEFAULT 0,
    total_cost_usd numeric(10,2),
    cost_per_message numeric(6,4),
    avg_satisfaction_score numeric(3,2),
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: daily_performance; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.daily_performance AS
 SELECT date,
    sum(total_messages) AS total_messages,
    sum(inbound_messages) AS inbound_messages,
    sum(outbound_messages) AS outbound_messages,
    avg(ai_success_rate) AS avg_ai_success_rate,
    avg(avg_response_time_seconds) AS avg_response_time,
    sum(total_cost_usd) AS total_cost,
    avg(avg_satisfaction_score) AS avg_satisfaction
   FROM public.message_analytics
  WHERE (hour IS NULL)
  GROUP BY date
  ORDER BY date DESC;


--
-- Name: data_sanitizer_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.data_sanitizer_log (
    id integer NOT NULL,
    run_id uuid NOT NULL,
    table_name text NOT NULL,
    column_name text NOT NULL,
    row_id text NOT NULL,
    original_value text,
    sanitized_value text,
    rule_applied text NOT NULL,
    anomalies text[],
    severity character varying(20) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT data_sanitizer_log_severity_check CHECK (((severity)::text = ANY ((ARRAY['auto_fix'::character varying, 'flag'::character varying, 'quarantine'::character varying])::text[])))
);


--
-- Name: data_sanitizer_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.data_sanitizer_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: data_sanitizer_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.data_sanitizer_log_id_seq OWNED BY public.data_sanitizer_log.id;


--
-- Name: deferred_api_writes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.deferred_api_writes (
    id integer NOT NULL,
    service text NOT NULL,
    method text NOT NULL,
    payload jsonb NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    max_attempts integer DEFAULT 10 NOT NULL,
    last_error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    next_retry_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: deferred_api_writes_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.deferred_api_writes_id_seq
    AS integer
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
-- Name: document_oracle_manifest; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.document_oracle_manifest (
    file_path text NOT NULL,
    sha256_hash text NOT NULL,
    chunk_count integer NOT NULL,
    sector text NOT NULL,
    ingested_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: email_archive; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.email_archive (
    id integer NOT NULL,
    category text,
    file_path text,
    sender text,
    subject text,
    content text,
    sent_at timestamp without time zone,
    is_mined boolean DEFAULT false,
    ts tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, ((COALESCE(subject, ''::text) || ' '::text) || COALESCE(content, ''::text)))) STORED,
    retry_count integer DEFAULT 0,
    last_error text,
    division text,
    division_confidence integer,
    division_summary text,
    is_vectorized boolean DEFAULT false,
    to_addresses text,
    cc_addresses text,
    bcc_addresses text,
    message_id text,
    ingested_from text
);


--
-- Name: email_archive_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.email_archive_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: email_archive_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.email_archive_id_seq OWNED BY public.email_archive.id;


--
-- Name: email_classification_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.email_classification_rules (
    id integer NOT NULL,
    division character varying(30) NOT NULL,
    match_field character varying(20) NOT NULL,
    pattern text NOT NULL,
    weight integer DEFAULT 10,
    is_regex boolean DEFAULT false,
    is_active boolean DEFAULT true,
    hit_count integer DEFAULT 0,
    notes text,
    created_at timestamp without time zone DEFAULT now(),
    CONSTRAINT email_classification_rules_match_field_check CHECK (((match_field)::text = ANY ((ARRAY['sender'::character varying, 'subject'::character varying, 'content'::character varying, 'any'::character varying])::text[]))),
    CONSTRAINT email_classification_rules_weight_check CHECK (((weight >= 1) AND (weight <= 100)))
);


--
-- Name: email_classification_rules_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.email_classification_rules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: email_classification_rules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.email_classification_rules_id_seq OWNED BY public.email_classification_rules.id;


--
-- Name: email_dead_letter_queue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.email_dead_letter_queue (
    id integer NOT NULL,
    fingerprint text NOT NULL,
    source_tag text,
    sender text,
    subject text,
    raw_payload jsonb NOT NULL,
    error_message text,
    error_traceback text,
    retry_count integer DEFAULT 0,
    max_retries integer DEFAULT 5,
    next_retry_at timestamp with time zone,
    status text DEFAULT 'pending'::text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT email_dead_letter_queue_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'retrying'::text, 'recovered'::text, 'dead'::text, 'manual_review'::text, 'discarded'::text])))
);


--
-- Name: email_dead_letter_queue_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.email_dead_letter_queue_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: email_dead_letter_queue_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.email_dead_letter_queue_id_seq OWNED BY public.email_dead_letter_queue.id;


--
-- Name: email_escalation_queue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.email_escalation_queue (
    id bigint NOT NULL,
    email_id bigint,
    trigger_type character varying(30) NOT NULL,
    trigger_detail text,
    priority character varying(5) DEFAULT 'P2'::character varying,
    status character varying(20) DEFAULT 'pending'::character varying,
    seen_by character varying(50),
    seen_at timestamp without time zone,
    action_taken text,
    created_at timestamp without time zone DEFAULT now(),
    snooze_until timestamp with time zone,
    CONSTRAINT email_escalation_queue_priority_check CHECK (((priority)::text = ANY ((ARRAY['P0'::character varying, 'P1'::character varying, 'P2'::character varying, 'P3'::character varying])::text[]))),
    CONSTRAINT email_escalation_queue_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'seen'::character varying, 'actioned'::character varying, 'dismissed'::character varying, 'snoozed'::character varying])::text[]))),
    CONSTRAINT email_escalation_queue_trigger_type_check CHECK (((trigger_type)::text = ANY ((ARRAY['vip_sender'::character varying, 'high_dollar'::character varying, 'legal_watchdog'::character varying, 'failed_classification'::character varying, 'negative_sentiment'::character varying, 'new_important_domain'::character varying, 'manual'::character varying, 'content_flag'::character varying])::text[])))
);


--
-- Name: email_escalation_queue_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.email_escalation_queue_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: email_escalation_queue_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.email_escalation_queue_id_seq OWNED BY public.email_escalation_queue.id;


--
-- Name: email_escalation_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.email_escalation_rules (
    id integer NOT NULL,
    rule_name character varying(100) NOT NULL,
    trigger_type character varying(30) NOT NULL,
    match_field character varying(20) NOT NULL,
    pattern text NOT NULL,
    priority character varying(5) DEFAULT 'P2'::character varying,
    is_active boolean DEFAULT true,
    notes text,
    created_at timestamp without time zone DEFAULT now(),
    CONSTRAINT email_escalation_rules_match_field_check CHECK (((match_field)::text = ANY ((ARRAY['sender'::character varying, 'subject'::character varying, 'content'::character varying, 'any'::character varying, 'amount'::character varying])::text[])))
);


--
-- Name: email_escalation_rules_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.email_escalation_rules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: email_escalation_rules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.email_escalation_rules_id_seq OWNED BY public.email_escalation_rules.id;


--
-- Name: email_intake_review_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.email_intake_review_log (
    id bigint NOT NULL,
    escalation_id bigint,
    email_id bigint,
    actor character varying(50) NOT NULL,
    action_type character varying(30) NOT NULL,
    old_division character varying(30),
    new_division character varying(30),
    old_confidence integer,
    new_confidence integer,
    review_grade integer,
    notes text,
    created_at timestamp without time zone DEFAULT now(),
    CONSTRAINT email_intake_review_log_action_type_check CHECK (((action_type)::text = ANY ((ARRAY['reclassify'::character varying, 'grade'::character varying, 'dismiss'::character varying, 'escalate'::character varying, 'approve'::character varying, 'add_rule'::character varying, 'bulk_action'::character varying])::text[]))),
    CONSTRAINT email_intake_review_log_review_grade_check CHECK (((review_grade IS NULL) OR ((review_grade >= 1) AND (review_grade <= 5))))
);


--
-- Name: email_intake_review_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.email_intake_review_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: email_intake_review_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.email_intake_review_log_id_seq OWNED BY public.email_intake_review_log.id;


--
-- Name: email_quarantine; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.email_quarantine (
    id bigint NOT NULL,
    sender text,
    subject text,
    content_preview text,
    sent_at timestamp without time zone,
    fingerprint character varying(64),
    source_tag character varying(30),
    rule_id integer,
    rule_type character varying(30),
    rule_reason text,
    status character varying(20) DEFAULT 'quarantined'::character varying,
    reviewed_by character varying(50),
    reviewed_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now(),
    CONSTRAINT email_quarantine_status_check CHECK (((status)::text = ANY ((ARRAY['quarantined'::character varying, 'released'::character varying, 'deleted'::character varying, 'reviewed'::character varying])::text[])))
);


--
-- Name: email_quarantine_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.email_quarantine_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: email_quarantine_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.email_quarantine_id_seq OWNED BY public.email_quarantine.id;


--
-- Name: email_routing_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.email_routing_rules (
    id integer NOT NULL,
    rule_type character varying(30) NOT NULL,
    pattern text NOT NULL,
    action character varying(20) NOT NULL,
    division character varying(30),
    reason text,
    is_active boolean DEFAULT true,
    hit_count integer DEFAULT 0,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    CONSTRAINT email_routing_rules_action_check CHECK (((action)::text = ANY ((ARRAY['REJECT'::character varying, 'QUARANTINE'::character varying, 'ALLOW'::character varying, 'ESCALATE'::character varying, 'PRIORITY'::character varying])::text[]))),
    CONSTRAINT email_routing_rules_rule_type_check CHECK (((rule_type)::text = ANY ((ARRAY['sender_block'::character varying, 'sender_vip'::character varying, 'domain_trust'::character varying, 'subject_block'::character varying, 'content_block'::character varying, 'sender_allow'::character varying])::text[])))
);


--
-- Name: email_routing_rules_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.email_routing_rules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: email_routing_rules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.email_routing_rules_id_seq OWNED BY public.email_routing_rules.id;


--
-- Name: email_sensors; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.email_sensors (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    email_address text NOT NULL,
    display_name text,
    protocol character varying(10) DEFAULT 'pop3'::character varying NOT NULL,
    server_address text NOT NULL,
    server_port integer DEFAULT 995 NOT NULL,
    encrypted_password text NOT NULL,
    use_ssl boolean DEFAULT true NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    last_sweep_at timestamp without time zone,
    last_sweep_status character varying(20) DEFAULT 'pending'::character varying,
    last_sweep_error text,
    emails_ingested_total integer DEFAULT 0,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    CONSTRAINT email_sensors_last_sweep_status_check CHECK (((last_sweep_status)::text = ANY ((ARRAY['green'::character varying, 'red'::character varying, 'pending'::character varying])::text[]))),
    CONSTRAINT email_sensors_protocol_check CHECK (((protocol)::text = ANY ((ARRAY['pop3'::character varying, 'imap'::character varying, 'gmail_api'::character varying])::text[])))
);


--
-- Name: email_triage_precedents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.email_triage_precedents (
    id integer NOT NULL,
    email_id integer,
    pattern_text text NOT NULL,
    division text NOT NULL,
    priority text DEFAULT 'P2'::text,
    reasoning text,
    created_by text DEFAULT 'HUMAN'::text,
    embedding public.vector(768),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: email_triage_precedents_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.email_triage_precedents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: email_triage_precedents_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.email_triage_precedents_id_seq OWNED BY public.email_triage_precedents.id;


--
-- Name: fin_owner_balances; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fin_owner_balances (
    property_id character varying(50) NOT NULL,
    property_name character varying(200),
    owner_name character varying(100),
    bedrooms integer,
    estimated_rate numeric(12,2),
    total_booked_nights integer DEFAULT 0,
    gross_revenue numeric(12,2) DEFAULT 0,
    mgmt_fee_pct numeric(5,2) DEFAULT 25.00,
    mgmt_fee_amount numeric(12,2) DEFAULT 0,
    owner_payout numeric(12,2) DEFAULT 0,
    last_calculated timestamp without time zone,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: fin_reservations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fin_reservations (
    res_id character varying(100) NOT NULL,
    property_id character varying(50),
    property_name character varying(200),
    guest_name character varying(100),
    check_in date,
    check_out date,
    nights integer,
    nightly_rate numeric(12,2),
    base_rent numeric(12,2),
    taxes numeric(12,2) DEFAULT 0,
    fees numeric(12,2) DEFAULT 0,
    total_revenue numeric(12,2),
    status character varying(50) DEFAULT 'Shadow-Booked'::character varying,
    source character varying(50) DEFAULT 'shadow'::character varying,
    is_estimation boolean DEFAULT true,
    confidence character varying(20) DEFAULT 'medium'::character varying,
    notes text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: fin_revenue_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fin_revenue_snapshots (
    snapshot_id integer NOT NULL,
    period_start date,
    period_end date,
    total_properties integer,
    total_nights integer,
    gross_revenue numeric(12,2),
    est_taxes numeric(12,2),
    est_mgmt_fees numeric(12,2),
    est_owner_payout numeric(12,2),
    source character varying(50) DEFAULT 'shadow'::character varying,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: fin_revenue_snapshots_snapshot_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.fin_revenue_snapshots_snapshot_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: fin_revenue_snapshots_snapshot_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.fin_revenue_snapshots_snapshot_id_seq OWNED BY public.fin_revenue_snapshots.snapshot_id;


--
-- Name: finance_invoices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_invoices (
    id integer NOT NULL,
    vendor text NOT NULL,
    amount numeric(10,2) NOT NULL,
    date date NOT NULL,
    category text,
    source_email_id integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: finance_invoices_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.finance_invoices_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: finance_invoices_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.finance_invoices_id_seq OWNED BY public.finance_invoices.id;


--
-- Name: fortress_api_keys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fortress_api_keys (
    id integer NOT NULL,
    key_prefix character varying(12) NOT NULL,
    key_hash character varying(255) NOT NULL,
    name character varying(100) NOT NULL,
    scopes text[] DEFAULT '{}'::text[],
    owner_id integer,
    is_active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT now(),
    last_used timestamp without time zone
);


--
-- Name: fortress_api_keys_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.fortress_api_keys_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: fortress_api_keys_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.fortress_api_keys_id_seq OWNED BY public.fortress_api_keys.id;


--
-- Name: fortress_users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fortress_users (
    id integer NOT NULL,
    username character varying(50) NOT NULL,
    email character varying(255),
    password character varying(255) NOT NULL,
    role character varying(20) DEFAULT 'viewer'::character varying NOT NULL,
    is_active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT now(),
    last_login timestamp without time zone,
    full_name character varying(100),
    web_ui_access boolean DEFAULT false NOT NULL,
    vrs_access boolean DEFAULT false NOT NULL,
    CONSTRAINT fortress_users_role_check CHECK (((role)::text = ANY ((ARRAY['admin'::character varying, 'operator'::character varying, 'viewer'::character varying])::text[])))
);


--
-- Name: fortress_users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.fortress_users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: fortress_users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.fortress_users_id_seq OWNED BY public.fortress_users.id;


--
-- Name: general_ledger; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.general_ledger (
    id integer NOT NULL,
    filepath text,
    filename text,
    extension text,
    file_size bigint,
    doc_type text,
    category text,
    vendor text,
    client_name text,
    date_detected text,
    amount numeric(15,2),
    tax_year text,
    cabin text,
    business text,
    confidence text,
    raw_text text,
    ai_json text,
    processed_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    phase integer DEFAULT 1
);


--
-- Name: general_ledger_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.general_ledger_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: general_ledger_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.general_ledger_id_seq OWNED BY public.general_ledger.id;


--
-- Name: godhead_query_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.godhead_query_log (
    id bigint NOT NULL,
    session_id uuid DEFAULT gen_random_uuid(),
    prompt text NOT NULL,
    vaults_queried text[],
    models_called text[],
    synthesis text,
    confidence numeric(4,3),
    metadata jsonb DEFAULT '{}'::jsonb,
    queried_at timestamp with time zone DEFAULT now()
);


--
-- Name: godhead_query_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.godhead_query_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: godhead_query_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.godhead_query_log_id_seq OWNED BY public.godhead_query_log.id;


--
-- Name: guest_leads; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.guest_leads (
    id integer NOT NULL,
    guest_name text,
    guest_email text,
    guest_phone text,
    event_type text,
    cabin_names text[],
    check_in date,
    check_out date,
    nights integer,
    guest_count integer,
    quoted_total numeric(12,2),
    status text DEFAULT 'inquiry'::text,
    source_email_id integer,
    email_direction text,
    thread_subject text,
    taylor_response_summary text,
    amenities_highlighted text[],
    notes text,
    extracted_at timestamp without time zone DEFAULT now()
);


--
-- Name: guest_leads_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.guest_leads_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: guest_leads_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.guest_leads_id_seq OWNED BY public.guest_leads.id;


--
-- Name: guest_profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.guest_profiles (
    id bigint NOT NULL,
    phone_number character varying(20) NOT NULL,
    name character varying(255),
    email character varying(255),
    alternate_phones character varying(20)[],
    total_messages integer DEFAULT 0,
    total_conversations integer DEFAULT 0,
    avg_response_time_seconds integer,
    preferred_contact_time character varying(20),
    typical_response_length character varying(20),
    common_intents text[],
    frequently_asked_questions text[],
    overall_sentiment character varying(20),
    sentiment_trend character varying(20),
    positive_interaction_ratio numeric(3,2),
    avg_satisfaction_score numeric(3,2),
    total_stays integer DEFAULT 0,
    favorite_cabins text[],
    lifetime_value numeric(10,2),
    last_stay_date date,
    next_booking_date date,
    communication_style character varying(50),
    language_preference character varying(10) DEFAULT 'en'::character varying,
    accessibility_needs text[],
    special_requests text[],
    vip_guest boolean DEFAULT false,
    requires_human_touch boolean DEFAULT false,
    do_not_contact boolean DEFAULT false,
    opted_out_at timestamp without time zone,
    first_contact timestamp without time zone,
    last_contact timestamp without time zone,
    days_since_last_contact integer,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    CONSTRAINT valid_overall_sentiment CHECK ((((overall_sentiment)::text = ANY ((ARRAY['positive'::character varying, 'neutral'::character varying, 'negative'::character varying, 'urgent'::character varying])::text[])) OR (overall_sentiment IS NULL)))
);


--
-- Name: guest_profiles_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.guest_profiles_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: guest_profiles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.guest_profiles_id_seq OWNED BY public.guest_profiles.id;


--
-- Name: images; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.images (
    id integer NOT NULL,
    filename text,
    path text,
    alt_text text,
    ai_description text,
    processed boolean DEFAULT false
);


--
-- Name: images_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.images_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: images_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.images_id_seq OWNED BY public.images.id;


--
-- Name: ingestion_dlq; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ingestion_dlq (
    id integer NOT NULL,
    source text NOT NULL,
    endpoint text,
    record_id text,
    payload jsonb NOT NULL,
    error_reason text NOT NULL,
    field_errors jsonb,
    resolved boolean DEFAULT false NOT NULL,
    resolved_at timestamp with time zone,
    resolved_by text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: ingestion_dlq_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ingestion_dlq_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ingestion_dlq_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ingestion_dlq_id_seq OWNED BY public.ingestion_dlq.id;


--
-- Name: journal_entries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.journal_entries (
    id integer NOT NULL,
    entry_date date NOT NULL,
    description text NOT NULL,
    reference_id text,
    reference_type text,
    property_id text,
    posted_by text DEFAULT 'system'::text,
    source_system text DEFAULT 'fortress'::text,
    is_void boolean DEFAULT false,
    void_reason text,
    voided_at timestamp without time zone,
    voided_by text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT journal_entries_reference_type_check CHECK ((reference_type = ANY (ARRAY['booking'::text, 'invoice'::text, 'payout'::text, 'adjustment'::text, 'cleaning_fee'::text, 'tax_remittance'::text, 'owner_draw'::text, 'security_deposit'::text, 'import'::text, 'manual'::text, NULL::text])))
);


--
-- Name: journal_entries_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.journal_entries_id_seq
    AS integer
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
    id integer NOT NULL,
    journal_entry_id integer NOT NULL,
    account_id integer NOT NULL,
    debit numeric(15,2) DEFAULT 0 NOT NULL,
    credit numeric(15,2) DEFAULT 0 NOT NULL,
    memo text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_non_negative CHECK (((debit >= (0)::numeric) AND (credit >= (0)::numeric))),
    CONSTRAINT chk_single_side CHECK ((((debit > (0)::numeric) AND (credit = (0)::numeric)) OR ((debit = (0)::numeric) AND (credit > (0)::numeric))))
);


--
-- Name: journal_line_items_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.journal_line_items_id_seq
    AS integer
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
-- Name: learning_judgments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.learning_judgments (
    id integer NOT NULL,
    agent_id text NOT NULL,
    metric_name text NOT NULL,
    predicted_value numeric(15,4),
    actual_value numeric(15,4),
    variance_pct numeric(8,4),
    passed boolean,
    action_taken text,
    context jsonb,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: learning_judgments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.learning_judgments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: learning_judgments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.learning_judgments_id_seq OWNED BY public.learning_judgments.id;


--
-- Name: learning_optimizations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.learning_optimizations (
    id integer NOT NULL,
    agent_id text NOT NULL,
    method text,
    old_prompt_hash text,
    new_prompt_hash text,
    reasoning text,
    failure_count integer,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: learning_optimizations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.learning_optimizations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: learning_optimizations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.learning_optimizations_id_seq OWNED BY public.learning_optimizations.id;


--
-- Name: legacy_cdc_checkpoints; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.legacy_cdc_checkpoints (
    stream_name text NOT NULL,
    log_file text,
    log_pos bigint,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: legacy_cdc_event_queue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.legacy_cdc_event_queue (
    id bigint NOT NULL,
    stream_name text NOT NULL,
    source_schema text,
    source_table text NOT NULL,
    operation text NOT NULL,
    primary_key jsonb NOT NULL,
    row_data jsonb,
    binlog_file text,
    binlog_pos bigint,
    event_time timestamp with time zone DEFAULT now() NOT NULL,
    state text DEFAULT 'queued'::text NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    last_error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    applied_at timestamp with time zone
);


--
-- Name: legacy_cdc_event_queue_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.legacy_cdc_event_queue_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: legacy_cdc_event_queue_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.legacy_cdc_event_queue_id_seq OWNED BY public.legacy_cdc_event_queue.id;


--
-- Name: legacy_cdc_row_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.legacy_cdc_row_state (
    source_schema text,
    source_table text NOT NULL,
    primary_key_hash text NOT NULL,
    primary_key jsonb NOT NULL,
    row_data jsonb,
    deleted boolean DEFAULT false NOT NULL,
    last_event_id bigint,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: legal_clients; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.legal_clients (
    client_id integer NOT NULL,
    name character varying(200) NOT NULL,
    industry character varying(100),
    contact_name character varying(200),
    contact_email character varying(200),
    notes text,
    status character varying(50) DEFAULT 'Active'::character varying,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: legal_clients_client_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.legal_clients_client_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: legal_clients_client_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.legal_clients_client_id_seq OWNED BY public.legal_clients.client_id;


--
-- Name: legal_docket; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.legal_docket (
    doc_id integer NOT NULL,
    matter_id character varying(50),
    doc_type character varying(50),
    title character varying(200) NOT NULL,
    content text,
    version integer DEFAULT 1,
    status character varying(50) DEFAULT 'Draft'::character varying,
    created_by character varying(100) DEFAULT 'system'::character varying,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: legal_docket_doc_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.legal_docket_doc_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: legal_docket_doc_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.legal_docket_doc_id_seq OWNED BY public.legal_docket.doc_id;


--
-- Name: legal_intel; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.legal_intel (
    id integer NOT NULL,
    case_name character varying(255),
    case_number character varying(100),
    court character varying(255),
    status character varying(100),
    priority character varying(50),
    next_deadline date,
    source_email_id integer,
    content text,
    created_at timestamp without time zone,
    enriched_at timestamp without time zone
);


--
-- Name: legal_intel_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.legal_intel_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: legal_intel_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.legal_intel_id_seq OWNED BY public.legal_intel.id;


--
-- Name: legal_matter_notes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.legal_matter_notes (
    note_id integer NOT NULL,
    matter_id character varying(50),
    agent character varying(50) DEFAULT 'user'::character varying,
    content text NOT NULL,
    note_type character varying(50) DEFAULT 'note'::character varying,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: legal_matter_notes_note_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.legal_matter_notes_note_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: legal_matter_notes_note_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.legal_matter_notes_note_id_seq OWNED BY public.legal_matter_notes.note_id;


--
-- Name: legal_matters; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.legal_matters (
    matter_id character varying(50) NOT NULL,
    client_id integer,
    title character varying(255) NOT NULL,
    practice_area character varying(100),
    description text,
    opposing_counsel character varying(200),
    jurisdiction character varying(100),
    status character varying(50) DEFAULT 'Open'::character varying,
    priority character varying(20) DEFAULT 'Normal'::character varying,
    strategy_notes text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: maintenance_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.maintenance_log (
    id integer NOT NULL,
    run_id text NOT NULL,
    cabin_name text NOT NULL,
    room_type text NOT NULL,
    room_display text,
    image_path text,
    image_hash text,
    image_size_bytes bigint,
    overall_score numeric(5,1),
    verdict text NOT NULL,
    pass_threshold integer DEFAULT 80,
    items_passed integer,
    items_failed integer,
    items_total integer,
    ai_confidence_score numeric(5,4),
    detected_by text,
    json_parsed boolean DEFAULT false,
    issues_found text,
    checklist_json text,
    overall_impression text,
    raw_analysis text,
    inspector_id text,
    inference_time_s real,
    engine_version text DEFAULT '1.0.0'::text,
    generated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: maintenance_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.maintenance_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: maintenance_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.maintenance_log_id_seq OWNED BY public.maintenance_log.id;


--
-- Name: market_intel; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.market_intel (
    id integer NOT NULL,
    ticker text,
    asset_class text,
    content text,
    signal_strength real,
    sent_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    source_file text,
    chunk_index integer,
    sender text,
    subject_line text,
    signal_direction text,
    broker text,
    action text,
    price numeric(15,4),
    source_email_id integer,
    enriched_at timestamp without time zone
);


--
-- Name: market_intel_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.market_intel_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: market_intel_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.market_intel_id_seq OWNED BY public.market_intel.id;


--
-- Name: market_signals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.market_signals (
    id integer NOT NULL,
    symbol text,
    price real,
    sentiment_score real,
    source text,
    "timestamp" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    ticker text,
    action text,
    confidence_score numeric(3,2),
    source_email_id integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: market_signals_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.market_signals_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: market_signals_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.market_signals_id_seq OWNED BY public.market_signals.id;


--
-- Name: message_analytics_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.message_analytics_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: message_analytics_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.message_analytics_id_seq OWNED BY public.message_analytics.id;


--
-- Name: message_archive_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.message_archive_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: message_archive_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.message_archive_id_seq OWNED BY public.message_archive.id;


--
-- Name: model_telemetry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.model_telemetry (
    id integer NOT NULL,
    model_name text NOT NULL,
    node text,
    operation text,
    success boolean,
    latency_ms integer,
    input_tokens integer,
    output_tokens integer,
    error_message text,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: model_telemetry_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.model_telemetry_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: model_telemetry_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.model_telemetry_id_seq OWNED BY public.model_telemetry.id;


--
-- Name: nas_legal_vault; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.nas_legal_vault (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    source_file text NOT NULL,
    chunk_index integer NOT NULL,
    chunk_text text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    embedding public.vector(768),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: nim_arm64_probe_results; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.nim_arm64_probe_results (
    id integer NOT NULL,
    probe_date date NOT NULL,
    image_path text NOT NULL,
    tag text NOT NULL,
    stage1_arm64 boolean,
    arm64_digest text,
    amd64_digest text,
    arm64_manifest_bytes integer,
    amd64_manifest_bytes integer,
    possible_mismatch boolean,
    verdict text,
    probe_notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: nim_arm64_probe_results_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.nim_arm64_probe_results_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: nim_arm64_probe_results_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.nim_arm64_probe_results_id_seq OWNED BY public.nim_arm64_probe_results.id;


--
-- Name: ops_crew; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ops_crew (
    id integer NOT NULL,
    name character varying(100) NOT NULL,
    role character varying(50) NOT NULL,
    phone character varying(20),
    email character varying(100),
    status character varying(20) DEFAULT 'ACTIVE'::character varying,
    current_location character varying(100),
    skills jsonb DEFAULT '{}'::jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: ops_crew_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ops_crew_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ops_crew_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ops_crew_id_seq OWNED BY public.ops_crew.id;


--
-- Name: ops_historical_guests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ops_historical_guests (
    id bigint NOT NULL,
    guest_id text NOT NULL,
    full_name text,
    email text,
    phone text,
    address text,
    reservation_history jsonb DEFAULT '[]'::jsonb NOT NULL,
    total_spend numeric(14,2) DEFAULT 0 NOT NULL,
    first_seen date,
    last_seen date,
    raw_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: ops_historical_guests_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ops_historical_guests_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ops_historical_guests_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ops_historical_guests_id_seq OWNED BY public.ops_historical_guests.id;


--
-- Name: ops_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ops_log (
    id integer NOT NULL,
    "timestamp" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    actor character varying(100),
    action text NOT NULL,
    entity_type character varying(50),
    entity_id integer,
    metadata jsonb
);


--
-- Name: ops_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ops_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ops_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ops_log_id_seq OWNED BY public.ops_log.id;


--
-- Name: ops_overrides; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ops_overrides (
    id integer NOT NULL,
    entity_type character varying(50) NOT NULL,
    entity_id character varying(100) NOT NULL,
    override_type character varying(50) NOT NULL,
    reason text,
    issued_by character varying(100) DEFAULT '''commander'''::character varying,
    effective_until timestamp without time zone,
    active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: ops_overrides_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ops_overrides_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ops_overrides_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ops_overrides_id_seq OWNED BY public.ops_overrides.id;


--
-- Name: ops_properties; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ops_properties (
    property_id character varying(50) NOT NULL,
    internal_name character varying(100),
    address text,
    access_code_wifi character varying(50),
    access_code_door character varying(50),
    trash_pickup_day character varying(20),
    cleaning_sla_minutes integer DEFAULT 240,
    hvac_filter_size character varying(20),
    hot_tub_gallons integer,
    config_yaml text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    streamline_id integer,
    name text,
    unit_code text,
    status_name text DEFAULT 'Active'::text,
    status_id integer DEFAULT 1,
    address2 text,
    city text,
    state_name text,
    zip text,
    country_name text,
    latitude numeric(10,7),
    longitude numeric(11,7),
    location_area_name text,
    resort_area_name text,
    view_name text,
    bedrooms numeric(4,1),
    bathrooms numeric(4,1),
    max_occupants integer,
    max_adults integer,
    max_pets integer,
    lodging_type_id integer,
    square_feet integer,
    company_id integer,
    owning_type_id integer,
    seo_title text,
    flyer_url text,
    default_image_url text,
    description_short text,
    streamline_created timestamp without time zone,
    last_reservation timestamp without time zone,
    last_synced timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    raw_json jsonb
);


--
-- Name: ops_tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ops_tasks (
    id integer NOT NULL,
    type character varying(50) NOT NULL,
    priority character varying(20) DEFAULT 'NORMAL'::character varying,
    property_id character varying(50),
    assigned_to integer,
    turnover_id integer,
    description text,
    deadline timestamp without time zone,
    started_at timestamp without time zone,
    completed_at timestamp without time zone,
    status character varying(50) DEFAULT 'OPEN'::character varying,
    evidence_photos jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: ops_tasks_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ops_tasks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ops_tasks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ops_tasks_id_seq OWNED BY public.ops_tasks.id;


--
-- Name: ops_turnovers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ops_turnovers (
    id integer NOT NULL,
    property_id character varying(50),
    reservation_id_out character varying(50),
    reservation_id_in character varying(50),
    checkout_time timestamp without time zone NOT NULL,
    checkin_time timestamp without time zone NOT NULL,
    window_hours numeric(5,2),
    status character varying(50) DEFAULT 'PENDING'::character varying,
    cleanliness_score integer,
    notes text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: ops_turnovers_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ops_turnovers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ops_turnovers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ops_turnovers_id_seq OWNED BY public.ops_turnovers.id;


--
-- Name: ops_visuals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ops_visuals (
    image_id integer NOT NULL,
    file_path text NOT NULL,
    file_name character varying(255),
    file_size_bytes bigint,
    file_ext character varying(10),
    property_id character varying(50),
    property_name character varying(200),
    description text,
    features jsonb DEFAULT '{}'::jsonb,
    room_type character varying(50),
    quality_score numeric(5,2),
    embedding_id character varying(100),
    collection_name character varying(100) DEFAULT 'fortress_docs'::character varying,
    model_used character varying(100),
    inference_time_s real,
    status character varying(20) DEFAULT 'PENDING'::character varying,
    error_message text,
    scanned_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    visual_hash character varying(64)
);


--
-- Name: ops_visuals_image_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ops_visuals_image_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ops_visuals_image_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ops_visuals_image_id_seq OWNED BY public.ops_visuals.image_id;


--
-- Name: pages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pages (
    id integer NOT NULL,
    url text,
    title text,
    content text,
    last_scraped timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: pages_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pages_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pages_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pages_id_seq OWNED BY public.pages.id;


--
-- Name: pending_reviews; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.pending_reviews AS
 SELECT arq.id,
    arq.phone_number,
    arq.guest_name,
    arq.cabin_name,
    arq.guest_message,
    arq.intent,
    arq.sentiment,
    arq.urgency_level,
    arq.escalation_required,
    arq.ai_draft,
    arq.confidence_score,
    arq.ai_model,
    arq.created_at,
    arq.expires_at,
    gp.communication_style,
    gp.total_stays,
    gp.vip_guest,
    gp.overall_sentiment AS guest_overall_sentiment
   FROM (public.agent_response_queue arq
     LEFT JOIN public.guest_profiles gp ON (((arq.phone_number)::text = (gp.phone_number)::text)))
  WHERE ((arq.status)::text = 'pending_review'::text)
  ORDER BY arq.urgency_level DESC, arq.created_at;


--
-- Name: persona_scores; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.persona_scores (
    persona_slug character varying(50) NOT NULL,
    persona_name character varying(100) NOT NULL,
    total_votes integer DEFAULT 0 NOT NULL,
    correct_votes integer DEFAULT 0 NOT NULL,
    brier_score double precision DEFAULT 0.0 NOT NULL,
    streak integer DEFAULT 0 NOT NULL,
    last_signal character varying(20),
    last_conviction double precision,
    last_voted_at timestamp with time zone,
    last_updated timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: properties; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.properties (
    id integer NOT NULL,
    name character varying(100) NOT NULL,
    address character varying(255),
    parcel_id character varying(50),
    county character varying(50) DEFAULT 'Fannin'::character varying,
    acres numeric(5,2),
    acquisition_date date,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    ownership_status character varying(20) DEFAULT 'UNKNOWN'::character varying NOT NULL,
    cost_basis numeric(12,2),
    current_value numeric(12,2),
    depreciation_start date,
    owner_contact_info jsonb,
    streamline_id integer,
    management_status character varying(20) DEFAULT 'active'::character varying,
    launch_date date
);


--
-- Name: properties_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.properties_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: properties_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.properties_id_seq OWNED BY public.properties.id;


--
-- Name: property_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.property_events (
    id integer NOT NULL,
    property_id integer,
    event_type character varying(50),
    event_date date,
    status character varying(20) DEFAULT 'PENDING'::character varying,
    notes text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: property_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.property_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: property_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.property_events_id_seq OWNED BY public.property_events.id;


--
-- Name: property_sms_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.property_sms_config (
    id integer NOT NULL,
    property_id integer NOT NULL,
    property_name character varying(255) NOT NULL,
    cabin_name character varying(100),
    assigned_phone_number character varying(20) NOT NULL,
    provider_id integer,
    ai_enabled boolean DEFAULT true,
    ai_model_preference character varying(100),
    auto_reply_enabled boolean DEFAULT true,
    require_human_approval boolean DEFAULT false,
    business_hours_start time without time zone,
    business_hours_end time without time zone,
    timezone character varying(50) DEFAULT 'America/New_York'::character varying,
    after_hours_behavior character varying(50),
    welcome_message_template text,
    checkin_info_template text,
    checkout_reminder_template text,
    wifi_info_template text,
    wifi_ssid character varying(100),
    wifi_password character varying(100),
    door_code character varying(20),
    address text,
    checkin_instructions text,
    house_rules text,
    emergency_contact character varying(20),
    escalation_phone character varying(20),
    escalation_email character varying(255),
    escalation_keywords text[],
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: property_sms_config_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.property_sms_config_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: property_sms_config_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.property_sms_config_id_seq OWNED BY public.property_sms_config.id;


--
-- Name: quarantine_inbox; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quarantine_inbox (
    id integer NOT NULL,
    sender text NOT NULL,
    subject text,
    content text,
    sent_at timestamp without time zone,
    blocked_by text NOT NULL,
    blocked_reason text,
    file_path text,
    category text,
    quarantined_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: quarantine_inbox_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.quarantine_inbox_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: quarantine_inbox_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.quarantine_inbox_id_seq OWNED BY public.quarantine_inbox.id;


--
-- Name: rag_query_feedback; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rag_query_feedback (
    id integer NOT NULL,
    query_text text NOT NULL,
    brain text,
    collection text,
    top_k integer,
    chunks_retrieved integer,
    relevance_score numeric(5,4),
    reranker_used boolean DEFAULT false,
    response_quality integer,
    latency_retrieval_ms integer,
    latency_llm_ms integer,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: rag_query_feedback_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.rag_query_feedback_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: rag_query_feedback_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.rag_query_feedback_id_seq OWNED BY public.rag_query_feedback.id;


--
-- Name: real_estate_intel; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.real_estate_intel (
    id integer NOT NULL,
    property_name character varying(255),
    property_value numeric(15,2),
    property_address text,
    zillow_estimate numeric(15,2),
    date date,
    source_email_id integer,
    raw_content text,
    created_at timestamp without time zone
);


--
-- Name: real_estate_intel_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.real_estate_intel_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: real_estate_intel_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.real_estate_intel_id_seq OWNED BY public.real_estate_intel.id;


--
-- Name: recent_conversations; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.recent_conversations AS
 SELECT ct.id AS thread_id,
    ct.phone_number,
    gp.name AS guest_name,
    ct.property_id,
    psc.cabin_name,
    ct.message_count,
    ct.status,
    ct.last_message_at,
    ct.handled_by_ai,
    gp.vip_guest,
    ( SELECT message_archive.message_body
           FROM public.message_archive
          WHERE ((message_archive.phone_number)::text = (ct.phone_number)::text)
          ORDER BY message_archive.sent_at DESC
         LIMIT 1) AS last_message
   FROM ((public.conversation_threads ct
     LEFT JOIN public.guest_profiles gp ON (((ct.phone_number)::text = (gp.phone_number)::text)))
     LEFT JOIN public.property_sms_config psc ON ((ct.property_id = psc.property_id)))
  WHERE ((ct.status)::text = 'active'::text)
  ORDER BY ct.last_message_at DESC;


--
-- Name: recursive_trace_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.recursive_trace_log (
    id integer NOT NULL,
    run_id text NOT NULL,
    user_id text,
    query text NOT NULL,
    step_number integer NOT NULL,
    stage text NOT NULL,
    content text,
    critic_score integer,
    critic_tags text[],
    model text,
    latency_ms integer,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: recursive_trace_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.recursive_trace_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: recursive_trace_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.recursive_trace_log_id_seq OWNED BY public.recursive_trace_log.id;


--
-- Name: revenue_ledger; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.revenue_ledger (
    id integer NOT NULL,
    run_id text NOT NULL,
    cabin_name text NOT NULL,
    target_date date NOT NULL,
    target_dow text,
    base_rate numeric(10,2),
    seasonal_baseline numeric(10,2),
    adjusted_rate numeric(10,2) NOT NULL,
    alpha numeric(10,2),
    previous_rate numeric(10,2),
    rate_change numeric(10,2),
    rate_change_pct numeric(6,2),
    sentiment_score numeric(6,4),
    weather_factor numeric(6,4),
    event_factor numeric(6,4),
    competitor_factor numeric(6,4),
    volatility_index numeric(6,4),
    trading_signal text,
    confidence numeric(6,4),
    weather_condition text,
    weather_temp_f real,
    event_name text,
    event_weight integer,
    competitor_direction text,
    competitor_rate_change numeric(10,2),
    days_until_checkin integer,
    engine_version text DEFAULT '1.0.0'::text,
    tier text,
    generated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: revenue_ledger_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.revenue_ledger_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: revenue_ledger_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.revenue_ledger_id_seq OWNED BY public.revenue_ledger.id;


--
-- Name: ruebarue_area_guide; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ruebarue_area_guide (
    id integer NOT NULL,
    section character varying(100) NOT NULL,
    entry_number integer,
    place_name text,
    address text,
    distance text,
    phone text,
    rating text,
    tip text,
    raw_text text NOT NULL,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: ruebarue_area_guide_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ruebarue_area_guide_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ruebarue_area_guide_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ruebarue_area_guide_id_seq OWNED BY public.ruebarue_area_guide.id;


--
-- Name: ruebarue_contacts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ruebarue_contacts (
    id integer NOT NULL,
    name character varying(200) NOT NULL,
    phone character varying(50),
    email character varying(200),
    role character varying(50),
    properties text,
    tags text,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: ruebarue_contacts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ruebarue_contacts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ruebarue_contacts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ruebarue_contacts_id_seq OWNED BY public.ruebarue_contacts.id;


--
-- Name: ruebarue_guests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ruebarue_guests (
    id integer NOT NULL,
    guest_info text NOT NULL,
    property_info text,
    door_code text,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: ruebarue_guests_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ruebarue_guests_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ruebarue_guests_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ruebarue_guests_id_seq OWNED BY public.ruebarue_guests.id;


--
-- Name: ruebarue_knowledge_base; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ruebarue_knowledge_base (
    id integer NOT NULL,
    category character varying(100) NOT NULL,
    subcategory character varying(100),
    title text NOT NULL,
    content text NOT NULL,
    source character varying(50) NOT NULL,
    property_name character varying(200),
    metadata jsonb,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: ruebarue_knowledge_base_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ruebarue_knowledge_base_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ruebarue_knowledge_base_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ruebarue_knowledge_base_id_seq OWNED BY public.ruebarue_knowledge_base.id;


--
-- Name: ruebarue_message_templates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ruebarue_message_templates (
    id integer NOT NULL,
    name character varying(200) NOT NULL,
    type character varying(20) NOT NULL,
    active boolean DEFAULT true,
    schedule character varying(200),
    tags text,
    booking_source character varying(200),
    flags text,
    subject text,
    message_text text,
    full_modal_text text,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: ruebarue_message_templates_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ruebarue_message_templates_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ruebarue_message_templates_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ruebarue_message_templates_id_seq OWNED BY public.ruebarue_message_templates.id;


--
-- Name: sales_intel; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sales_intel (
    id integer NOT NULL,
    signal_type text,
    cabin_name text,
    event_type text,
    check_in date,
    check_out date,
    nights integer,
    guest_count integer,
    total_quoted numeric(12,2),
    bedrooms integer,
    selling_points text[],
    guest_objections text,
    conversion_outcome text,
    competitive_mention text,
    source_email_id integer,
    extracted_at timestamp without time zone DEFAULT now()
);


--
-- Name: sales_intel_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sales_intel_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sales_intel_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sales_intel_id_seq OWNED BY public.sales_intel.id;


--
-- Name: schema_drift_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_drift_log (
    id integer NOT NULL,
    endpoint text NOT NULL,
    model_name text NOT NULL,
    unknown_keys jsonb NOT NULL,
    sample_values jsonb,
    record_id text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: schema_drift_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.schema_drift_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: schema_drift_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.schema_drift_log_id_seq OWNED BY public.schema_drift_log.id;


--
-- Name: sender_registry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sender_registry (
    id integer NOT NULL,
    sender_raw text NOT NULL,
    email_address text,
    display_name text,
    domain text,
    status character varying(20) DEFAULT 'REVIEW'::character varying,
    division character varying(50),
    total_volume integer DEFAULT 0,
    mined_count integer DEFAULT 0,
    empty_extraction_count integer DEFAULT 0,
    last_seen timestamp without time zone,
    signal_ratio double precision GENERATED ALWAYS AS (
CASE
    WHEN (total_volume = 0) THEN (0)::double precision
    ELSE ((mined_count)::double precision / (total_volume)::double precision)
END) STORED,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: sender_registry_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sender_registry_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sender_registry_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sender_registry_id_seq OWNED BY public.sender_registry.id;


--
-- Name: sentinel_alerts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sentinel_alerts (
    id integer NOT NULL,
    source text NOT NULL,
    name text NOT NULL,
    priority text NOT NULL,
    message text NOT NULL,
    arm64 boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: sentinel_alerts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sentinel_alerts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sentinel_alerts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sentinel_alerts_id_seq OWNED BY public.sentinel_alerts.id;


--
-- Name: sentinel_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sentinel_state (
    key text NOT NULL,
    value text NOT NULL,
    source text DEFAULT 'unknown'::text NOT NULL,
    priority text DEFAULT 'MEDIUM'::text NOT NULL,
    note text DEFAULT ''::text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: sms_providers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sms_providers (
    id integer NOT NULL,
    name character varying(50) NOT NULL,
    account_sid character varying(255),
    auth_token_encrypted text,
    phone_numbers text[],
    supports_mms boolean DEFAULT false,
    supports_unicode boolean DEFAULT true,
    max_message_length integer DEFAULT 160,
    priority integer DEFAULT 100,
    enabled boolean DEFAULT true,
    cost_per_message numeric(6,4),
    cost_per_segment numeric(6,4),
    monthly_fee numeric(8,2),
    total_messages_sent integer DEFAULT 0,
    success_rate numeric(5,4),
    avg_delivery_time_seconds integer,
    last_failure_at timestamp without time zone,
    consecutive_failures integer DEFAULT 0,
    rate_limit_per_second integer,
    rate_limit_per_minute integer,
    rate_limit_per_hour integer,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: sms_providers_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sms_providers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sms_providers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sms_providers_id_seq OWNED BY public.sms_providers.id;


--
-- Name: sovereign_cycles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sovereign_cycles (
    id integer NOT NULL,
    cycle_id integer NOT NULL,
    "timestamp" timestamp with time zone DEFAULT now() NOT NULL,
    health_status text NOT NULL,
    health_score real,
    directives jsonb DEFAULT '[]'::jsonb,
    optimization_triggers jsonb DEFAULT '[]'::jsonb,
    division_a_summary jsonb,
    division_b_summary jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: sovereign_cycles_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sovereign_cycles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sovereign_cycles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sovereign_cycles_id_seq OWNED BY public.sovereign_cycles.id;


--
-- Name: starred_responses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.starred_responses (
    id integer NOT NULL,
    message_body text NOT NULL,
    embedding public.vector(768),
    intent character varying(100),
    cabin_name character varying(200),
    guest_name character varying(200),
    phone_number_hash character varying(64),
    loyalty_tier character varying(50),
    response_type character varying(20) DEFAULT 'approved'::character varying NOT NULL,
    quality_grade integer,
    queue_id bigint,
    ai_model character varying(100),
    original_draft text,
    edit_distance_pct numeric(5,2),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: starred_responses_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.starred_responses_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: starred_responses_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.starred_responses_id_seq OWNED BY public.starred_responses.id;


--
-- Name: sys_api_credentials; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sys_api_credentials (
    service_name character varying(255) NOT NULL,
    token_key character varying(255) NOT NULL,
    token_secret character varying(255) NOT NULL,
    expiration_date timestamp with time zone,
    last_updated timestamp with time zone DEFAULT now()
);


--
-- Name: system_directives; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.system_directives (
    id bigint NOT NULL,
    directive_text text NOT NULL,
    source_failure_cluster character varying(512),
    embedding_metadata jsonb DEFAULT '{}'::jsonb,
    active boolean DEFAULT true NOT NULL,
    version smallint DEFAULT '1'::smallint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: system_directives_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.system_directives_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: system_directives_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.system_directives_id_seq OWNED BY public.system_directives.id;


--
-- Name: system_drift_alerts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.system_drift_alerts (
    id integer NOT NULL,
    run_id text NOT NULL,
    intent text NOT NULL,
    metric text NOT NULL,
    current_value numeric NOT NULL,
    threshold numeric NOT NULL,
    sample_count integer NOT NULL,
    detail text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: system_drift_alerts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.system_drift_alerts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: system_drift_alerts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.system_drift_alerts_id_seq OWNED BY public.system_drift_alerts.id;


--
-- Name: system_post_mortems; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.system_post_mortems (
    id integer NOT NULL,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL,
    sector character varying(10) NOT NULL,
    severity character varying(10) NOT NULL,
    component text NOT NULL,
    error_summary text NOT NULL,
    root_cause text,
    remediation text,
    status character varying(20) DEFAULT 'open'::character varying,
    resolved_by character varying(50),
    resolved_at timestamp with time zone
);


--
-- Name: system_post_mortems_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.system_post_mortems_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: system_post_mortems_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.system_post_mortems_id_seq OWNED BY public.system_post_mortems.id;


--
-- Name: system_telemetry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.system_telemetry (
    id integer NOT NULL,
    hostname text,
    cpu_usage real,
    ram_usage real,
    disk_usage real,
    recorded_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: system_telemetry_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.system_telemetry_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: system_telemetry_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.system_telemetry_id_seq OWNED BY public.system_telemetry.id;


--
-- Name: trust_balance; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trust_balance (
    id integer NOT NULL,
    property_id text NOT NULL,
    owner_funds numeric(15,2) DEFAULT 0 NOT NULL,
    operating_funds numeric(15,2) DEFAULT 0 NOT NULL,
    escrow_funds numeric(15,2) DEFAULT 0 NOT NULL,
    security_deps numeric(15,2) DEFAULT 0 NOT NULL,
    last_entry_id integer,
    last_updated timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: trust_balance_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.trust_balance_id_seq
    AS integer
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
-- Name: v_property_lifecycle; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_property_lifecycle AS
 SELECT op.property_id,
    op.name AS display_name,
    op.bedrooms,
    op.max_occupants,
    op.city,
    op.streamline_id,
    op.status_name AS ops_status,
    p.management_status,
    p.launch_date,
    p.cost_basis,
    p.current_value,
        CASE
            WHEN ((p.management_status)::text = 'retired'::text) THEN 'RETIRED'::text
            WHEN (op.status_name = 'Retired'::text) THEN 'ORPHAN'::text
            WHEN ((p.launch_date IS NOT NULL) AND (p.launch_date > (CURRENT_DATE - '90 days'::interval))) THEN 'RAMP_UP'::text
            ELSE 'MATURE'::text
        END AS lifecycle_stage,
    (COALESCE(r.forecast_revenue, (0)::numeric))::numeric(12,2) AS forecast_revenue,
    (COALESCE(r.avg_nightly, (0)::numeric))::numeric(10,2) AS avg_nightly_rate,
    COALESCE(r.entry_count, (0)::bigint) AS rate_entries,
    COALESCE(t.open_tasks, (0)::bigint) AS open_tasks,
    COALESCE(t.urgent_tasks, (0)::bigint) AS urgent_tasks,
    COALESCE(t.overdue_tasks, (0)::bigint) AS overdue_tasks,
    t.next_deadline
   FROM (((public.ops_properties op
     LEFT JOIN public.properties p ON ((p.streamline_id = op.streamline_id)))
     LEFT JOIN ( SELECT revenue_ledger.cabin_name,
            sum(revenue_ledger.adjusted_rate) AS forecast_revenue,
            avg(revenue_ledger.adjusted_rate) AS avg_nightly,
            count(*) AS entry_count
           FROM public.revenue_ledger
          GROUP BY revenue_ledger.cabin_name) r ON ((r.cabin_name = (op.property_id)::text)))
     LEFT JOIN ( SELECT ops_tasks.property_id,
            count(*) AS open_tasks,
            count(*) FILTER (WHERE ((ops_tasks.priority)::text = 'URGENT'::text)) AS urgent_tasks,
            count(*) FILTER (WHERE (ops_tasks.deadline < now())) AS overdue_tasks,
            min(ops_tasks.deadline) AS next_deadline
           FROM public.ops_tasks
          WHERE ((ops_tasks.status)::text = 'OPEN'::text)
          GROUP BY ops_tasks.property_id) t ON (((t.property_id)::text = (op.property_id)::text)));


--
-- Name: v_comp_dashboard; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_comp_dashboard AS
 SELECT ( SELECT (COALESCE(sum(rl.adjusted_rate), (0)::numeric))::numeric(12,2) AS "coalesce"
           FROM public.revenue_ledger rl
          WHERE (EXISTS ( SELECT 1
                   FROM public.ops_properties op
                  WHERE (((op.property_id)::text = rl.cabin_name) AND (op.status_name = 'Active'::text))))) AS forecast_revenue,
    ( SELECT (avg(rl.adjusted_rate))::numeric(10,2) AS avg
           FROM public.revenue_ledger rl
          WHERE (EXISTS ( SELECT 1
                   FROM public.ops_properties op
                  WHERE (((op.property_id)::text = rl.cabin_name) AND (op.status_name = 'Active'::text))))) AS avg_nightly_rate,
    ( SELECT count(DISTINCT rl.cabin_name) AS count
           FROM public.revenue_ledger rl
          WHERE (EXISTS ( SELECT 1
                   FROM public.ops_properties op
                  WHERE (((op.property_id)::text = rl.cabin_name) AND (op.status_name = 'Active'::text))))) AS active_cabins,
    ( SELECT count(*) AS count
           FROM public.v_property_lifecycle
          WHERE (v_property_lifecycle.lifecycle_stage = 'RAMP_UP'::text)) AS cabins_in_ramp_up,
    ( SELECT (COALESCE(sum(fi.amount), (0)::numeric))::numeric(14,2) AS "coalesce"
           FROM (public.finance_invoices fi
             JOIN finance.vendor_classifications vc ON ((fi.vendor ~~ vc.vendor_pattern)))
          WHERE (vc.classification = 'REAL_BUSINESS'::text)) AS real_business_expenses,
    ( SELECT (COALESCE(sum(fi.amount), (0)::numeric))::numeric(14,2) AS "coalesce"
           FROM (public.finance_invoices fi
             JOIN finance.vendor_classifications vc ON ((fi.vendor ~~ vc.vendor_pattern)))
          WHERE (vc.classification = ANY (ARRAY['NOISE'::text, 'FAMILY_INTERNAL'::text, 'CROG_INTERNAL'::text]))) AS excluded_noise_total,
    ( SELECT (COALESCE(sum(fi.amount), (0)::numeric))::numeric(14,2) AS "coalesce"
           FROM (public.finance_invoices fi
             LEFT JOIN finance.vendor_classifications vc ON ((fi.vendor ~~ vc.vendor_pattern)))
          WHERE (vc.classification IS NULL)) AS unclassified_total,
    ( SELECT (COALESCE(sum(
                CASE
                    WHEN (transactions.amount > (0)::numeric) THEN transactions.amount
                    ELSE (0)::numeric
                END), (0)::numeric))::numeric(12,2) AS "coalesce"
           FROM division_a.transactions) AS ledger_credits,
    ( SELECT (COALESCE(sum(
                CASE
                    WHEN (transactions.amount < (0)::numeric) THEN abs(transactions.amount)
                    ELSE (0)::numeric
                END), (0)::numeric))::numeric(12,2) AS "coalesce"
           FROM division_a.transactions) AS ledger_debits,
    (( SELECT (COALESCE(sum(rl.adjusted_rate), (0)::numeric))::numeric(12,2) AS "coalesce"
           FROM public.revenue_ledger rl
          WHERE (EXISTS ( SELECT 1
                   FROM public.ops_properties op
                  WHERE (((op.property_id)::text = rl.cabin_name) AND (op.status_name = 'Active'::text))))) + ( SELECT (COALESCE(sum(transactions.amount), (0)::numeric))::numeric(12,2) AS "coalesce"
           FROM division_a.transactions)) AS corrected_revenue,
    ( SELECT (COALESCE(sum(rl.adjusted_rate), (0)::numeric))::numeric(12,2) AS "coalesce"
           FROM public.revenue_ledger rl
          WHERE (NOT (EXISTS ( SELECT 1
                   FROM public.ops_properties op
                  WHERE (((op.property_id)::text = rl.cabin_name) AND (op.status_name = 'Active'::text)))))) AS excluded_retired_revenue,
    now() AS report_timestamp,
    'TITAN-R1-671B v2 (2026-02-13)'::text AS classified_by;


--
-- Name: v_financial_summary; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_financial_summary AS
 WITH forecast AS (
         SELECT 'FORECAST'::text AS source,
            revenue_ledger.cabin_name AS entity,
            revenue_ledger.target_date AS entry_date,
            revenue_ledger.adjusted_rate AS amount,
            revenue_ledger.trading_signal AS category,
            revenue_ledger.run_id AS reference,
            'Pricing engine forecast rate'::text AS description
           FROM public.revenue_ledger
        ), invoices AS (
         SELECT 'INVOICE'::text AS source,
            fi.vendor AS entity,
            fi.date AS entry_date,
            fi.amount,
            COALESCE(fi.category, 'Uncategorized'::text) AS category,
            ('INV-'::text || (fi.id)::text) AS reference,
                CASE
                    WHEN (vc.classification IS NOT NULL) THEN (('['::text || vc.classification) || '] Email-extracted invoice'::text)
                    ELSE 'Email-extracted invoice (UNCLASSIFIED)'::text
                END AS description
           FROM (public.finance_invoices fi
             LEFT JOIN finance.vendor_classifications vc ON ((fi.vendor ~~ vc.vendor_pattern)))
          WHERE ((vc.classification IS NULL) OR (vc.classification = 'REAL_BUSINESS'::text) OR (vc.classification = 'UNKNOWN'::text))
        ), transactions AS (
         SELECT 'LEDGER'::text AS source,
            transactions.vendor AS entity,
            transactions.date AS entry_date,
            transactions.amount,
            COALESCE(transactions.category, 'Uncategorized'::text) AS category,
            ('TXN-'::text || (transactions.id)::text) AS reference,
            COALESCE(transactions.reasoning, 'Double-entry transaction'::text) AS description
           FROM division_a.transactions
        )
 SELECT forecast.source,
    forecast.entity,
    forecast.entry_date,
    forecast.amount,
    forecast.category,
    forecast.reference,
    forecast.description
   FROM forecast
UNION ALL
 SELECT invoices.source,
    invoices.entity,
    invoices.entry_date,
    invoices.amount,
    invoices.category,
    invoices.reference,
    invoices.description
   FROM invoices
UNION ALL
 SELECT transactions.source,
    transactions.entity,
    transactions.entry_date,
    transactions.amount,
    transactions.category,
    transactions.reference,
    transactions.description
   FROM transactions;


--
-- Name: v_journal_detail; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_journal_detail AS
 SELECT je.id AS entry_id,
    je.entry_date,
    je.description,
    je.reference_id,
    je.reference_type,
    je.property_id,
    je.posted_by,
    je.source_system,
    je.is_void,
    jli.id AS line_id,
    a.code AS account_code,
    a.name AS account_name,
    a.account_type,
    jli.debit,
    jli.credit,
    jli.memo,
    je.created_at
   FROM ((public.journal_entries je
     JOIN public.journal_line_items jli ON ((jli.journal_entry_id = je.id)))
     JOIN public.accounts a ON ((a.id = jli.account_id)))
  ORDER BY je.entry_date DESC, je.id, jli.id;


--
-- Name: v_trial_balance; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_trial_balance AS
 SELECT a.id AS account_id,
    a.code,
    a.name AS account_name,
    a.account_type,
    a.normal_balance,
    COALESCE(sum(jli.debit), (0)::numeric) AS total_debits,
    COALESCE(sum(jli.credit), (0)::numeric) AS total_credits,
    (COALESCE(sum(jli.debit), (0)::numeric) - COALESCE(sum(jli.credit), (0)::numeric)) AS net_balance
   FROM ((public.accounts a
     LEFT JOIN public.journal_line_items jli ON ((jli.account_id = a.id)))
     LEFT JOIN public.journal_entries je ON (((je.id = jli.journal_entry_id) AND (je.is_void = false))))
  WHERE (a.is_active = true)
  GROUP BY a.id, a.code, a.name, a.account_type, a.normal_balance
  ORDER BY a.code;


--
-- Name: v_trust_summary; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_trust_summary AS
 SELECT property_id,
    owner_funds,
    operating_funds,
    escrow_funds,
    security_deps,
    (((owner_funds + operating_funds) + escrow_funds) + security_deps) AS total_funds,
    last_updated
   FROM public.trust_balance
  ORDER BY property_id;


--
-- Name: vault_alpha_state_law; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vault_alpha_state_law (
    id integer NOT NULL,
    code_section text NOT NULL,
    statute_text text NOT NULL,
    embedding public.vector(768),
    text_search tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, statute_text)) STORED,
    title text,
    metadata jsonb DEFAULT '{}'::jsonb,
    inserted_at timestamp with time zone DEFAULT now()
);


--
-- Name: vault_alpha_state_law_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.vault_alpha_state_law_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vault_alpha_state_law_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.vault_alpha_state_law_id_seq OWNED BY public.vault_alpha_state_law.id;


--
-- Name: vault_beta_federal_law; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vault_beta_federal_law (
    id integer NOT NULL,
    title_chapter_section text NOT NULL,
    statute_text text NOT NULL,
    embedding public.vector(768),
    text_search tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, statute_text)) STORED,
    title text,
    metadata jsonb DEFAULT '{}'::jsonb,
    inserted_at timestamp with time zone DEFAULT now()
);


--
-- Name: vault_beta_federal_law_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.vault_beta_federal_law_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vault_beta_federal_law_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.vault_beta_federal_law_id_seq OWNED BY public.vault_beta_federal_law.id;


--
-- Name: vault_delta; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vault_delta (
    id integer NOT NULL,
    citation character varying(100) NOT NULL,
    case_name text NOT NULL,
    court character varying(150),
    date_decided date,
    docket_number character varying(100),
    opinion_type character varying(30),
    author character varying(150),
    chunk_index integer NOT NULL,
    chunk_text text NOT NULL,
    embedding public.vector(768),
    source_file character varying(255),
    topics text[],
    created_at timestamp without time zone DEFAULT now(),
    text_search tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, ((((COALESCE(chunk_text, ''::text) || ' '::text) || COALESCE(case_name, ''::text)) || ' '::text) || (COALESCE(citation, ''::character varying))::text))) STORED
);


--
-- Name: vault_delta_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.vault_delta_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vault_delta_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.vault_delta_id_seq OWNED BY public.vault_delta.id;


--
-- Name: vault_gamma_evidence; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vault_gamma_evidence (
    id integer NOT NULL,
    file_hash text NOT NULL,
    file_path text NOT NULL,
    metadata jsonb,
    raw_text text NOT NULL,
    embedding public.vector(768),
    text_search tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, raw_text)) STORED,
    doc_type text,
    parties text[],
    date_authored date,
    inserted_at timestamp with time zone DEFAULT now()
);


--
-- Name: vault_gamma_evidence_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.vault_gamma_evidence_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vault_gamma_evidence_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.vault_gamma_evidence_id_seq OWNED BY public.vault_gamma_evidence.id;


--
-- Name: vision_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vision_runs (
    run_id integer NOT NULL,
    scan_path text NOT NULL,
    model_used character varying(100),
    images_found integer DEFAULT 0,
    images_processed integer DEFAULT 0,
    images_failed integer DEFAULT 0,
    images_skipped integer DEFAULT 0,
    started_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    completed_at timestamp without time zone,
    status character varying(20) DEFAULT 'RUNNING'::character varying
);


--
-- Name: vision_runs_run_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.vision_runs_run_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vision_runs_run_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.vision_runs_run_id_seq OWNED BY public.vision_runs.run_id;


--
-- Name: account_mappings id; Type: DEFAULT; Schema: division_a; Owner: -
--

ALTER TABLE ONLY division_a.account_mappings ALTER COLUMN id SET DEFAULT nextval('division_a.account_mappings_id_seq'::regclass);


--
-- Name: audit_log id; Type: DEFAULT; Schema: division_a; Owner: -
--

ALTER TABLE ONLY division_a.audit_log ALTER COLUMN id SET DEFAULT nextval('division_a.audit_log_id_seq'::regclass);


--
-- Name: chart_of_accounts id; Type: DEFAULT; Schema: division_a; Owner: -
--

ALTER TABLE ONLY division_a.chart_of_accounts ALTER COLUMN id SET DEFAULT nextval('division_a.chart_of_accounts_id_seq'::regclass);


--
-- Name: general_ledger id; Type: DEFAULT; Schema: division_a; Owner: -
--

ALTER TABLE ONLY division_a.general_ledger ALTER COLUMN id SET DEFAULT nextval('division_a.general_ledger_id_seq'::regclass);


--
-- Name: journal_entries id; Type: DEFAULT; Schema: division_a; Owner: -
--

ALTER TABLE ONLY division_a.journal_entries ALTER COLUMN id SET DEFAULT nextval('division_a.journal_entries_id_seq'::regclass);


--
-- Name: predictions id; Type: DEFAULT; Schema: division_a; Owner: -
--

ALTER TABLE ONLY division_a.predictions ALTER COLUMN id SET DEFAULT nextval('division_a.predictions_id_seq'::regclass);


--
-- Name: transactions id; Type: DEFAULT; Schema: division_a; Owner: -
--

ALTER TABLE ONLY division_a.transactions ALTER COLUMN id SET DEFAULT nextval('division_a.transactions_id_seq'::regclass);


--
-- Name: account_mappings id; Type: DEFAULT; Schema: division_b; Owner: -
--

ALTER TABLE ONLY division_b.account_mappings ALTER COLUMN id SET DEFAULT nextval('division_b.account_mappings_id_seq'::regclass);


--
-- Name: chart_of_accounts id; Type: DEFAULT; Schema: division_b; Owner: -
--

ALTER TABLE ONLY division_b.chart_of_accounts ALTER COLUMN id SET DEFAULT nextval('division_b.chart_of_accounts_id_seq'::regclass);


--
-- Name: escrow id; Type: DEFAULT; Schema: division_b; Owner: -
--

ALTER TABLE ONLY division_b.escrow ALTER COLUMN id SET DEFAULT nextval('division_b.escrow_id_seq'::regclass);


--
-- Name: general_ledger id; Type: DEFAULT; Schema: division_b; Owner: -
--

ALTER TABLE ONLY division_b.general_ledger ALTER COLUMN id SET DEFAULT nextval('division_b.general_ledger_id_seq'::regclass);


--
-- Name: journal_entries id; Type: DEFAULT; Schema: division_b; Owner: -
--

ALTER TABLE ONLY division_b.journal_entries ALTER COLUMN id SET DEFAULT nextval('division_b.journal_entries_id_seq'::regclass);


--
-- Name: predictions id; Type: DEFAULT; Schema: division_b; Owner: -
--

ALTER TABLE ONLY division_b.predictions ALTER COLUMN id SET DEFAULT nextval('division_b.predictions_id_seq'::regclass);


--
-- Name: transactions id; Type: DEFAULT; Schema: division_b; Owner: -
--

ALTER TABLE ONLY division_b.transactions ALTER COLUMN id SET DEFAULT nextval('division_b.transactions_id_seq'::regclass);


--
-- Name: trust_ledger id; Type: DEFAULT; Schema: division_b; Owner: -
--

ALTER TABLE ONLY division_b.trust_ledger ALTER COLUMN id SET DEFAULT nextval('division_b.trust_ledger_id_seq'::regclass);


--
-- Name: vendor_payouts id; Type: DEFAULT; Schema: division_b; Owner: -
--

ALTER TABLE ONLY division_b.vendor_payouts ALTER COLUMN id SET DEFAULT nextval('division_b.vendor_payouts_id_seq'::regclass);


--
-- Name: change_orders id; Type: DEFAULT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.change_orders ALTER COLUMN id SET DEFAULT nextval('engineering.change_orders_id_seq'::regclass);


--
-- Name: compliance_log id; Type: DEFAULT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.compliance_log ALTER COLUMN id SET DEFAULT nextval('engineering.compliance_log_id_seq'::regclass);


--
-- Name: cost_estimates id; Type: DEFAULT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.cost_estimates ALTER COLUMN id SET DEFAULT nextval('engineering.cost_estimates_id_seq'::regclass);


--
-- Name: drawings id; Type: DEFAULT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.drawings ALTER COLUMN id SET DEFAULT nextval('engineering.drawings_id_seq'::regclass);


--
-- Name: inspections id; Type: DEFAULT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.inspections ALTER COLUMN id SET DEFAULT nextval('engineering.inspections_id_seq'::regclass);


--
-- Name: mep_systems id; Type: DEFAULT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.mep_systems ALTER COLUMN id SET DEFAULT nextval('engineering.mep_systems_id_seq'::regclass);


--
-- Name: permits id; Type: DEFAULT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.permits ALTER COLUMN id SET DEFAULT nextval('engineering.permits_id_seq'::regclass);


--
-- Name: projects id; Type: DEFAULT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.projects ALTER COLUMN id SET DEFAULT nextval('engineering.projects_id_seq'::regclass);


--
-- Name: punch_items id; Type: DEFAULT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.punch_items ALTER COLUMN id SET DEFAULT nextval('engineering.punch_items_id_seq'::regclass);


--
-- Name: rfis id; Type: DEFAULT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.rfis ALTER COLUMN id SET DEFAULT nextval('engineering.rfis_id_seq'::regclass);


--
-- Name: submittals id; Type: DEFAULT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.submittals ALTER COLUMN id SET DEFAULT nextval('engineering.submittals_id_seq'::regclass);


--
-- Name: classification_rules id; Type: DEFAULT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.classification_rules ALTER COLUMN id SET DEFAULT nextval('finance.classification_rules_id_seq'::regclass);


--
-- Name: vendor_classifications id; Type: DEFAULT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.vendor_classifications ALTER COLUMN id SET DEFAULT nextval('finance.vendor_classifications_id_seq'::regclass);


--
-- Name: active_strategies id; Type: DEFAULT; Schema: hedge_fund; Owner: -
--

ALTER TABLE ONLY hedge_fund.active_strategies ALTER COLUMN id SET DEFAULT nextval('hedge_fund.active_strategies_id_seq'::regclass);


--
-- Name: extraction_log id; Type: DEFAULT; Schema: hedge_fund; Owner: -
--

ALTER TABLE ONLY hedge_fund.extraction_log ALTER COLUMN id SET DEFAULT nextval('hedge_fund.extraction_log_id_seq'::regclass);


--
-- Name: market_signals id; Type: DEFAULT; Schema: hedge_fund; Owner: -
--

ALTER TABLE ONLY hedge_fund.market_signals ALTER COLUMN id SET DEFAULT nextval('hedge_fund.market_signals_id_seq'::regclass);


--
-- Name: watchlist id; Type: DEFAULT; Schema: hedge_fund; Owner: -
--

ALTER TABLE ONLY hedge_fund.watchlist ALTER COLUMN id SET DEFAULT nextval('hedge_fund.watchlist_id_seq'::regclass);


--
-- Name: entities id; Type: DEFAULT; Schema: intelligence; Owner: -
--

ALTER TABLE ONLY intelligence.entities ALTER COLUMN id SET DEFAULT nextval('intelligence.entities_id_seq'::regclass);


--
-- Name: golden_reasoning id; Type: DEFAULT; Schema: intelligence; Owner: -
--

ALTER TABLE ONLY intelligence.golden_reasoning ALTER COLUMN id SET DEFAULT nextval('intelligence.golden_reasoning_id_seq'::regclass);


--
-- Name: relationships id; Type: DEFAULT; Schema: intelligence; Owner: -
--

ALTER TABLE ONLY intelligence.relationships ALTER COLUMN id SET DEFAULT nextval('intelligence.relationships_id_seq'::regclass);


--
-- Name: titan_traces id; Type: DEFAULT; Schema: intelligence; Owner: -
--

ALTER TABLE ONLY intelligence.titan_traces ALTER COLUMN id SET DEFAULT nextval('intelligence.titan_traces_id_seq'::regclass);


--
-- Name: case_actions id; Type: DEFAULT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.case_actions ALTER COLUMN id SET DEFAULT nextval('legal.case_actions_id_seq'::regclass);


--
-- Name: case_evidence id; Type: DEFAULT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.case_evidence ALTER COLUMN id SET DEFAULT nextval('legal.case_evidence_id_seq'::regclass);


--
-- Name: case_precedents id; Type: DEFAULT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.case_precedents ALTER COLUMN id SET DEFAULT nextval('legal.case_precedents_id_seq'::regclass);


--
-- Name: case_watchdog id; Type: DEFAULT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.case_watchdog ALTER COLUMN id SET DEFAULT nextval('legal.case_watchdog_id_seq'::regclass);


--
-- Name: cases id; Type: DEFAULT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.cases ALTER COLUMN id SET DEFAULT nextval('legal.cases_id_seq'::regclass);


--
-- Name: correspondence id; Type: DEFAULT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.correspondence ALTER COLUMN id SET DEFAULT nextval('legal.correspondence_id_seq'::regclass);


--
-- Name: deadlines id; Type: DEFAULT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.deadlines ALTER COLUMN id SET DEFAULT nextval('legal.deadlines_id_seq'::regclass);


--
-- Name: email_intake_queue id; Type: DEFAULT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.email_intake_queue ALTER COLUMN id SET DEFAULT nextval('legal.email_intake_queue_id_seq'::regclass);


--
-- Name: expense_intake id; Type: DEFAULT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.expense_intake ALTER COLUMN id SET DEFAULT nextval('legal.expense_intake_id_seq'::regclass);


--
-- Name: filings id; Type: DEFAULT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.filings ALTER COLUMN id SET DEFAULT nextval('legal.filings_id_seq'::regclass);


--
-- Name: timeline_events id; Type: DEFAULT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.timeline_events ALTER COLUMN id SET DEFAULT nextval('legal.timeline_events_id_seq'::regclass);


--
-- Name: uploads id; Type: DEFAULT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.uploads ALTER COLUMN id SET DEFAULT nextval('legal.uploads_id_seq'::regclass);


--
-- Name: attorney_scoring id; Type: DEFAULT; Schema: legal_cmd; Owner: -
--

ALTER TABLE ONLY legal_cmd.attorney_scoring ALTER COLUMN id SET DEFAULT nextval('legal_cmd.attorney_scoring_id_seq'::regclass);


--
-- Name: ab_test_observations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ab_test_observations ALTER COLUMN id SET DEFAULT nextval('public.ab_test_observations_id_seq'::regclass);


--
-- Name: ab_tests id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ab_tests ALTER COLUMN id SET DEFAULT nextval('public.ab_tests_id_seq'::regclass);


--
-- Name: accounts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts ALTER COLUMN id SET DEFAULT nextval('public.accounts_id_seq'::regclass);


--
-- Name: active_learning_queue id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.active_learning_queue ALTER COLUMN id SET DEFAULT nextval('public.active_learning_queue_id_seq'::regclass);


--
-- Name: agent_learning_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_learning_log ALTER COLUMN id SET DEFAULT nextval('public.agent_learning_log_id_seq'::regclass);


--
-- Name: agent_memory id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_memory ALTER COLUMN id SET DEFAULT nextval('public.agent_memory_id_seq'::regclass);


--
-- Name: agent_performance_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_performance_log ALTER COLUMN id SET DEFAULT nextval('public.agent_performance_log_id_seq'::regclass);


--
-- Name: agent_response_queue id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_response_queue ALTER COLUMN id SET DEFAULT nextval('public.agent_response_queue_id_seq'::regclass);


--
-- Name: agent_telemetry id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_telemetry ALTER COLUMN id SET DEFAULT nextval('public.agent_telemetry_id_seq'::regclass);


--
-- Name: ai_training_labels id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_training_labels ALTER COLUMN id SET DEFAULT nextval('public.ai_training_labels_id_seq'::regclass);


--
-- Name: anomaly_flags id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.anomaly_flags ALTER COLUMN id SET DEFAULT nextval('public.anomaly_flags_id_seq'::regclass);


--
-- Name: api_key_vault id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_key_vault ALTER COLUMN id SET DEFAULT nextval('public.api_key_vault_id_seq'::regclass);


--
-- Name: asset_docs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_docs ALTER COLUMN id SET DEFAULT nextval('public.asset_docs_id_seq'::regclass);


--
-- Name: conversation_threads id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_threads ALTER COLUMN id SET DEFAULT nextval('public.conversation_threads_id_seq'::regclass);


--
-- Name: data_sanitizer_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_sanitizer_log ALTER COLUMN id SET DEFAULT nextval('public.data_sanitizer_log_id_seq'::regclass);


--
-- Name: deferred_api_writes id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deferred_api_writes ALTER COLUMN id SET DEFAULT nextval('public.deferred_api_writes_id_seq'::regclass);


--
-- Name: email_archive id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_archive ALTER COLUMN id SET DEFAULT nextval('public.email_archive_id_seq'::regclass);


--
-- Name: email_classification_rules id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_classification_rules ALTER COLUMN id SET DEFAULT nextval('public.email_classification_rules_id_seq'::regclass);


--
-- Name: email_dead_letter_queue id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_dead_letter_queue ALTER COLUMN id SET DEFAULT nextval('public.email_dead_letter_queue_id_seq'::regclass);


--
-- Name: email_escalation_queue id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_escalation_queue ALTER COLUMN id SET DEFAULT nextval('public.email_escalation_queue_id_seq'::regclass);


--
-- Name: email_escalation_rules id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_escalation_rules ALTER COLUMN id SET DEFAULT nextval('public.email_escalation_rules_id_seq'::regclass);


--
-- Name: email_intake_review_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_intake_review_log ALTER COLUMN id SET DEFAULT nextval('public.email_intake_review_log_id_seq'::regclass);


--
-- Name: email_quarantine id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_quarantine ALTER COLUMN id SET DEFAULT nextval('public.email_quarantine_id_seq'::regclass);


--
-- Name: email_routing_rules id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_routing_rules ALTER COLUMN id SET DEFAULT nextval('public.email_routing_rules_id_seq'::regclass);


--
-- Name: email_triage_precedents id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_triage_precedents ALTER COLUMN id SET DEFAULT nextval('public.email_triage_precedents_id_seq'::regclass);


--
-- Name: fin_revenue_snapshots snapshot_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fin_revenue_snapshots ALTER COLUMN snapshot_id SET DEFAULT nextval('public.fin_revenue_snapshots_snapshot_id_seq'::regclass);


--
-- Name: finance_invoices id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_invoices ALTER COLUMN id SET DEFAULT nextval('public.finance_invoices_id_seq'::regclass);


--
-- Name: fortress_api_keys id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fortress_api_keys ALTER COLUMN id SET DEFAULT nextval('public.fortress_api_keys_id_seq'::regclass);


--
-- Name: fortress_users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fortress_users ALTER COLUMN id SET DEFAULT nextval('public.fortress_users_id_seq'::regclass);


--
-- Name: general_ledger id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.general_ledger ALTER COLUMN id SET DEFAULT nextval('public.general_ledger_id_seq'::regclass);


--
-- Name: godhead_query_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.godhead_query_log ALTER COLUMN id SET DEFAULT nextval('public.godhead_query_log_id_seq'::regclass);


--
-- Name: guest_leads id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.guest_leads ALTER COLUMN id SET DEFAULT nextval('public.guest_leads_id_seq'::regclass);


--
-- Name: guest_profiles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.guest_profiles ALTER COLUMN id SET DEFAULT nextval('public.guest_profiles_id_seq'::regclass);


--
-- Name: images id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.images ALTER COLUMN id SET DEFAULT nextval('public.images_id_seq'::regclass);


--
-- Name: ingestion_dlq id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ingestion_dlq ALTER COLUMN id SET DEFAULT nextval('public.ingestion_dlq_id_seq'::regclass);


--
-- Name: journal_entries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_entries ALTER COLUMN id SET DEFAULT nextval('public.journal_entries_id_seq'::regclass);


--
-- Name: journal_line_items id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_line_items ALTER COLUMN id SET DEFAULT nextval('public.journal_line_items_id_seq'::regclass);


--
-- Name: learning_judgments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learning_judgments ALTER COLUMN id SET DEFAULT nextval('public.learning_judgments_id_seq'::regclass);


--
-- Name: learning_optimizations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learning_optimizations ALTER COLUMN id SET DEFAULT nextval('public.learning_optimizations_id_seq'::regclass);


--
-- Name: legacy_cdc_event_queue id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legacy_cdc_event_queue ALTER COLUMN id SET DEFAULT nextval('public.legacy_cdc_event_queue_id_seq'::regclass);


--
-- Name: legal_clients client_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legal_clients ALTER COLUMN client_id SET DEFAULT nextval('public.legal_clients_client_id_seq'::regclass);


--
-- Name: legal_docket doc_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legal_docket ALTER COLUMN doc_id SET DEFAULT nextval('public.legal_docket_doc_id_seq'::regclass);


--
-- Name: legal_intel id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legal_intel ALTER COLUMN id SET DEFAULT nextval('public.legal_intel_id_seq'::regclass);


--
-- Name: legal_matter_notes note_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legal_matter_notes ALTER COLUMN note_id SET DEFAULT nextval('public.legal_matter_notes_note_id_seq'::regclass);


--
-- Name: maintenance_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_log ALTER COLUMN id SET DEFAULT nextval('public.maintenance_log_id_seq'::regclass);


--
-- Name: market_intel id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.market_intel ALTER COLUMN id SET DEFAULT nextval('public.market_intel_id_seq'::regclass);


--
-- Name: market_signals id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.market_signals ALTER COLUMN id SET DEFAULT nextval('public.market_signals_id_seq'::regclass);


--
-- Name: message_analytics id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_analytics ALTER COLUMN id SET DEFAULT nextval('public.message_analytics_id_seq'::regclass);


--
-- Name: message_archive id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_archive ALTER COLUMN id SET DEFAULT nextval('public.message_archive_id_seq'::regclass);


--
-- Name: model_telemetry id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_telemetry ALTER COLUMN id SET DEFAULT nextval('public.model_telemetry_id_seq'::regclass);


--
-- Name: nim_arm64_probe_results id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nim_arm64_probe_results ALTER COLUMN id SET DEFAULT nextval('public.nim_arm64_probe_results_id_seq'::regclass);


--
-- Name: ops_crew id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ops_crew ALTER COLUMN id SET DEFAULT nextval('public.ops_crew_id_seq'::regclass);


--
-- Name: ops_historical_guests id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ops_historical_guests ALTER COLUMN id SET DEFAULT nextval('public.ops_historical_guests_id_seq'::regclass);


--
-- Name: ops_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ops_log ALTER COLUMN id SET DEFAULT nextval('public.ops_log_id_seq'::regclass);


--
-- Name: ops_overrides id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ops_overrides ALTER COLUMN id SET DEFAULT nextval('public.ops_overrides_id_seq'::regclass);


--
-- Name: ops_tasks id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ops_tasks ALTER COLUMN id SET DEFAULT nextval('public.ops_tasks_id_seq'::regclass);


--
-- Name: ops_turnovers id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ops_turnovers ALTER COLUMN id SET DEFAULT nextval('public.ops_turnovers_id_seq'::regclass);


--
-- Name: ops_visuals image_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ops_visuals ALTER COLUMN image_id SET DEFAULT nextval('public.ops_visuals_image_id_seq'::regclass);


--
-- Name: pages id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pages ALTER COLUMN id SET DEFAULT nextval('public.pages_id_seq'::regclass);


--
-- Name: properties id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.properties ALTER COLUMN id SET DEFAULT nextval('public.properties_id_seq'::regclass);


--
-- Name: property_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.property_events ALTER COLUMN id SET DEFAULT nextval('public.property_events_id_seq'::regclass);


--
-- Name: property_sms_config id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.property_sms_config ALTER COLUMN id SET DEFAULT nextval('public.property_sms_config_id_seq'::regclass);


--
-- Name: quarantine_inbox id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quarantine_inbox ALTER COLUMN id SET DEFAULT nextval('public.quarantine_inbox_id_seq'::regclass);


--
-- Name: rag_query_feedback id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rag_query_feedback ALTER COLUMN id SET DEFAULT nextval('public.rag_query_feedback_id_seq'::regclass);


--
-- Name: real_estate_intel id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.real_estate_intel ALTER COLUMN id SET DEFAULT nextval('public.real_estate_intel_id_seq'::regclass);


--
-- Name: recursive_trace_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recursive_trace_log ALTER COLUMN id SET DEFAULT nextval('public.recursive_trace_log_id_seq'::regclass);


--
-- Name: revenue_ledger id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.revenue_ledger ALTER COLUMN id SET DEFAULT nextval('public.revenue_ledger_id_seq'::regclass);


--
-- Name: ruebarue_area_guide id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ruebarue_area_guide ALTER COLUMN id SET DEFAULT nextval('public.ruebarue_area_guide_id_seq'::regclass);


--
-- Name: ruebarue_contacts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ruebarue_contacts ALTER COLUMN id SET DEFAULT nextval('public.ruebarue_contacts_id_seq'::regclass);


--
-- Name: ruebarue_guests id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ruebarue_guests ALTER COLUMN id SET DEFAULT nextval('public.ruebarue_guests_id_seq'::regclass);


--
-- Name: ruebarue_knowledge_base id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ruebarue_knowledge_base ALTER COLUMN id SET DEFAULT nextval('public.ruebarue_knowledge_base_id_seq'::regclass);


--
-- Name: ruebarue_message_templates id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ruebarue_message_templates ALTER COLUMN id SET DEFAULT nextval('public.ruebarue_message_templates_id_seq'::regclass);


--
-- Name: sales_intel id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sales_intel ALTER COLUMN id SET DEFAULT nextval('public.sales_intel_id_seq'::regclass);


--
-- Name: schema_drift_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_drift_log ALTER COLUMN id SET DEFAULT nextval('public.schema_drift_log_id_seq'::regclass);


--
-- Name: sender_registry id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sender_registry ALTER COLUMN id SET DEFAULT nextval('public.sender_registry_id_seq'::regclass);


--
-- Name: sentinel_alerts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sentinel_alerts ALTER COLUMN id SET DEFAULT nextval('public.sentinel_alerts_id_seq'::regclass);


--
-- Name: sms_providers id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sms_providers ALTER COLUMN id SET DEFAULT nextval('public.sms_providers_id_seq'::regclass);


--
-- Name: sovereign_cycles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sovereign_cycles ALTER COLUMN id SET DEFAULT nextval('public.sovereign_cycles_id_seq'::regclass);


--
-- Name: starred_responses id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.starred_responses ALTER COLUMN id SET DEFAULT nextval('public.starred_responses_id_seq'::regclass);


--
-- Name: system_directives id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_directives ALTER COLUMN id SET DEFAULT nextval('public.system_directives_id_seq'::regclass);


--
-- Name: system_drift_alerts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_drift_alerts ALTER COLUMN id SET DEFAULT nextval('public.system_drift_alerts_id_seq'::regclass);


--
-- Name: system_post_mortems id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_post_mortems ALTER COLUMN id SET DEFAULT nextval('public.system_post_mortems_id_seq'::regclass);


--
-- Name: system_telemetry id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_telemetry ALTER COLUMN id SET DEFAULT nextval('public.system_telemetry_id_seq'::regclass);


--
-- Name: trust_balance id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trust_balance ALTER COLUMN id SET DEFAULT nextval('public.trust_balance_id_seq'::regclass);


--
-- Name: vault_alpha_state_law id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_alpha_state_law ALTER COLUMN id SET DEFAULT nextval('public.vault_alpha_state_law_id_seq'::regclass);


--
-- Name: vault_beta_federal_law id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_beta_federal_law ALTER COLUMN id SET DEFAULT nextval('public.vault_beta_federal_law_id_seq'::regclass);


--
-- Name: vault_delta id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_delta ALTER COLUMN id SET DEFAULT nextval('public.vault_delta_id_seq'::regclass);


--
-- Name: vault_gamma_evidence id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_gamma_evidence ALTER COLUMN id SET DEFAULT nextval('public.vault_gamma_evidence_id_seq'::regclass);


--
-- Name: vision_runs run_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vision_runs ALTER COLUMN run_id SET DEFAULT nextval('public.vision_runs_run_id_seq'::regclass);


--
-- Name: account_mappings account_mappings_pkey; Type: CONSTRAINT; Schema: division_a; Owner: -
--

ALTER TABLE ONLY division_a.account_mappings
    ADD CONSTRAINT account_mappings_pkey PRIMARY KEY (id);


--
-- Name: audit_log audit_log_pkey; Type: CONSTRAINT; Schema: division_a; Owner: -
--

ALTER TABLE ONLY division_a.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (id);


--
-- Name: chart_of_accounts chart_of_accounts_code_key; Type: CONSTRAINT; Schema: division_a; Owner: -
--

ALTER TABLE ONLY division_a.chart_of_accounts
    ADD CONSTRAINT chart_of_accounts_code_key UNIQUE (code);


--
-- Name: chart_of_accounts chart_of_accounts_pkey; Type: CONSTRAINT; Schema: division_a; Owner: -
--

ALTER TABLE ONLY division_a.chart_of_accounts
    ADD CONSTRAINT chart_of_accounts_pkey PRIMARY KEY (id);


--
-- Name: general_ledger general_ledger_pkey; Type: CONSTRAINT; Schema: division_a; Owner: -
--

ALTER TABLE ONLY division_a.general_ledger
    ADD CONSTRAINT general_ledger_pkey PRIMARY KEY (id);


--
-- Name: journal_entries journal_entries_entry_id_key; Type: CONSTRAINT; Schema: division_a; Owner: -
--

ALTER TABLE ONLY division_a.journal_entries
    ADD CONSTRAINT journal_entries_entry_id_key UNIQUE (entry_id);


--
-- Name: journal_entries journal_entries_pkey; Type: CONSTRAINT; Schema: division_a; Owner: -
--

ALTER TABLE ONLY division_a.journal_entries
    ADD CONSTRAINT journal_entries_pkey PRIMARY KEY (id);


--
-- Name: predictions predictions_pkey; Type: CONSTRAINT; Schema: division_a; Owner: -
--

ALTER TABLE ONLY division_a.predictions
    ADD CONSTRAINT predictions_pkey PRIMARY KEY (id);


--
-- Name: transactions transactions_pkey; Type: CONSTRAINT; Schema: division_a; Owner: -
--

ALTER TABLE ONLY division_a.transactions
    ADD CONSTRAINT transactions_pkey PRIMARY KEY (id);


--
-- Name: transactions transactions_plaid_txn_id_key; Type: CONSTRAINT; Schema: division_a; Owner: -
--

ALTER TABLE ONLY division_a.transactions
    ADD CONSTRAINT transactions_plaid_txn_id_key UNIQUE (plaid_txn_id);


--
-- Name: account_mappings unique_vendor_mapping; Type: CONSTRAINT; Schema: division_a; Owner: -
--

ALTER TABLE ONLY division_a.account_mappings
    ADD CONSTRAINT unique_vendor_mapping UNIQUE (vendor_name);


--
-- Name: account_mappings account_mappings_pkey; Type: CONSTRAINT; Schema: division_b; Owner: -
--

ALTER TABLE ONLY division_b.account_mappings
    ADD CONSTRAINT account_mappings_pkey PRIMARY KEY (id);


--
-- Name: chart_of_accounts chart_of_accounts_code_key; Type: CONSTRAINT; Schema: division_b; Owner: -
--

ALTER TABLE ONLY division_b.chart_of_accounts
    ADD CONSTRAINT chart_of_accounts_code_key UNIQUE (code);


--
-- Name: chart_of_accounts chart_of_accounts_pkey; Type: CONSTRAINT; Schema: division_b; Owner: -
--

ALTER TABLE ONLY division_b.chart_of_accounts
    ADD CONSTRAINT chart_of_accounts_pkey PRIMARY KEY (id);


--
-- Name: escrow escrow_pkey; Type: CONSTRAINT; Schema: division_b; Owner: -
--

ALTER TABLE ONLY division_b.escrow
    ADD CONSTRAINT escrow_pkey PRIMARY KEY (id);


--
-- Name: escrow escrow_reservation_id_key; Type: CONSTRAINT; Schema: division_b; Owner: -
--

ALTER TABLE ONLY division_b.escrow
    ADD CONSTRAINT escrow_reservation_id_key UNIQUE (reservation_id);


--
-- Name: general_ledger general_ledger_pkey; Type: CONSTRAINT; Schema: division_b; Owner: -
--

ALTER TABLE ONLY division_b.general_ledger
    ADD CONSTRAINT general_ledger_pkey PRIMARY KEY (id);


--
-- Name: journal_entries journal_entries_entry_id_key; Type: CONSTRAINT; Schema: division_b; Owner: -
--

ALTER TABLE ONLY division_b.journal_entries
    ADD CONSTRAINT journal_entries_entry_id_key UNIQUE (entry_id);


--
-- Name: journal_entries journal_entries_pkey; Type: CONSTRAINT; Schema: division_b; Owner: -
--

ALTER TABLE ONLY division_b.journal_entries
    ADD CONSTRAINT journal_entries_pkey PRIMARY KEY (id);


--
-- Name: predictions predictions_pkey; Type: CONSTRAINT; Schema: division_b; Owner: -
--

ALTER TABLE ONLY division_b.predictions
    ADD CONSTRAINT predictions_pkey PRIMARY KEY (id);


--
-- Name: transactions transactions_pkey; Type: CONSTRAINT; Schema: division_b; Owner: -
--

ALTER TABLE ONLY division_b.transactions
    ADD CONSTRAINT transactions_pkey PRIMARY KEY (id);


--
-- Name: transactions transactions_plaid_txn_id_key; Type: CONSTRAINT; Schema: division_b; Owner: -
--

ALTER TABLE ONLY division_b.transactions
    ADD CONSTRAINT transactions_plaid_txn_id_key UNIQUE (plaid_txn_id);


--
-- Name: trust_ledger trust_ledger_pkey; Type: CONSTRAINT; Schema: division_b; Owner: -
--

ALTER TABLE ONLY division_b.trust_ledger
    ADD CONSTRAINT trust_ledger_pkey PRIMARY KEY (id);


--
-- Name: account_mappings unique_vendor_mapping; Type: CONSTRAINT; Schema: division_b; Owner: -
--

ALTER TABLE ONLY division_b.account_mappings
    ADD CONSTRAINT unique_vendor_mapping UNIQUE (vendor_name);


--
-- Name: vendor_payouts vendor_payouts_pkey; Type: CONSTRAINT; Schema: division_b; Owner: -
--

ALTER TABLE ONLY division_b.vendor_payouts
    ADD CONSTRAINT vendor_payouts_pkey PRIMARY KEY (id);


--
-- Name: change_orders change_orders_pkey; Type: CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.change_orders
    ADD CONSTRAINT change_orders_pkey PRIMARY KEY (id);


--
-- Name: compliance_log compliance_log_pkey; Type: CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.compliance_log
    ADD CONSTRAINT compliance_log_pkey PRIMARY KEY (id);


--
-- Name: cost_estimates cost_estimates_pkey; Type: CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.cost_estimates
    ADD CONSTRAINT cost_estimates_pkey PRIMARY KEY (id);


--
-- Name: drawings drawings_file_path_key; Type: CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.drawings
    ADD CONSTRAINT drawings_file_path_key UNIQUE (file_path);


--
-- Name: drawings drawings_pkey; Type: CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.drawings
    ADD CONSTRAINT drawings_pkey PRIMARY KEY (id);


--
-- Name: inspections inspections_pkey; Type: CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.inspections
    ADD CONSTRAINT inspections_pkey PRIMARY KEY (id);


--
-- Name: mep_systems mep_systems_pkey; Type: CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.mep_systems
    ADD CONSTRAINT mep_systems_pkey PRIMARY KEY (id);


--
-- Name: permits permits_permit_number_key; Type: CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.permits
    ADD CONSTRAINT permits_permit_number_key UNIQUE (permit_number);


--
-- Name: permits permits_pkey; Type: CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.permits
    ADD CONSTRAINT permits_pkey PRIMARY KEY (id);


--
-- Name: projects projects_pkey; Type: CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.projects
    ADD CONSTRAINT projects_pkey PRIMARY KEY (id);


--
-- Name: projects projects_project_code_key; Type: CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.projects
    ADD CONSTRAINT projects_project_code_key UNIQUE (project_code);


--
-- Name: punch_items punch_items_pkey; Type: CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.punch_items
    ADD CONSTRAINT punch_items_pkey PRIMARY KEY (id);


--
-- Name: rfis rfis_pkey; Type: CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.rfis
    ADD CONSTRAINT rfis_pkey PRIMARY KEY (id);


--
-- Name: submittals submittals_pkey; Type: CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.submittals
    ADD CONSTRAINT submittals_pkey PRIMARY KEY (id);


--
-- Name: classification_rules classification_rules_pkey; Type: CONSTRAINT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.classification_rules
    ADD CONSTRAINT classification_rules_pkey PRIMARY KEY (id);


--
-- Name: vendor_classifications vendor_classifications_pkey; Type: CONSTRAINT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.vendor_classifications
    ADD CONSTRAINT vendor_classifications_pkey PRIMARY KEY (id);


--
-- Name: vendor_classifications vendor_classifications_vendor_pattern_key; Type: CONSTRAINT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.vendor_classifications
    ADD CONSTRAINT vendor_classifications_vendor_pattern_key UNIQUE (vendor_pattern);


--
-- Name: active_strategies active_strategies_pkey; Type: CONSTRAINT; Schema: hedge_fund; Owner: -
--

ALTER TABLE ONLY hedge_fund.active_strategies
    ADD CONSTRAINT active_strategies_pkey PRIMARY KEY (id);


--
-- Name: extraction_log extraction_log_pkey; Type: CONSTRAINT; Schema: hedge_fund; Owner: -
--

ALTER TABLE ONLY hedge_fund.extraction_log
    ADD CONSTRAINT extraction_log_pkey PRIMARY KEY (id);


--
-- Name: market_signals market_signals_pkey; Type: CONSTRAINT; Schema: hedge_fund; Owner: -
--

ALTER TABLE ONLY hedge_fund.market_signals
    ADD CONSTRAINT market_signals_pkey PRIMARY KEY (id);


--
-- Name: watchlist watchlist_pkey; Type: CONSTRAINT; Schema: hedge_fund; Owner: -
--

ALTER TABLE ONLY hedge_fund.watchlist
    ADD CONSTRAINT watchlist_pkey PRIMARY KEY (id);


--
-- Name: watchlist watchlist_ticker_key; Type: CONSTRAINT; Schema: hedge_fund; Owner: -
--

ALTER TABLE ONLY hedge_fund.watchlist
    ADD CONSTRAINT watchlist_ticker_key UNIQUE (ticker);


--
-- Name: entities entities_entity_key_key; Type: CONSTRAINT; Schema: intelligence; Owner: -
--

ALTER TABLE ONLY intelligence.entities
    ADD CONSTRAINT entities_entity_key_key UNIQUE (entity_key);


--
-- Name: entities entities_pkey; Type: CONSTRAINT; Schema: intelligence; Owner: -
--

ALTER TABLE ONLY intelligence.entities
    ADD CONSTRAINT entities_pkey PRIMARY KEY (id);


--
-- Name: golden_reasoning golden_reasoning_pkey; Type: CONSTRAINT; Schema: intelligence; Owner: -
--

ALTER TABLE ONLY intelligence.golden_reasoning
    ADD CONSTRAINT golden_reasoning_pkey PRIMARY KEY (id);


--
-- Name: relationships relationships_from_entity_id_to_entity_id_relationship_type_key; Type: CONSTRAINT; Schema: intelligence; Owner: -
--

ALTER TABLE ONLY intelligence.relationships
    ADD CONSTRAINT relationships_from_entity_id_to_entity_id_relationship_type_key UNIQUE (from_entity_id, to_entity_id, relationship_type);


--
-- Name: relationships relationships_pkey; Type: CONSTRAINT; Schema: intelligence; Owner: -
--

ALTER TABLE ONLY intelligence.relationships
    ADD CONSTRAINT relationships_pkey PRIMARY KEY (id);


--
-- Name: titan_traces titan_traces_pkey; Type: CONSTRAINT; Schema: intelligence; Owner: -
--

ALTER TABLE ONLY intelligence.titan_traces
    ADD CONSTRAINT titan_traces_pkey PRIMARY KEY (id);


--
-- Name: case_actions case_actions_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.case_actions
    ADD CONSTRAINT case_actions_pkey PRIMARY KEY (id);


--
-- Name: case_evidence case_evidence_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.case_evidence
    ADD CONSTRAINT case_evidence_pkey PRIMARY KEY (id);


--
-- Name: case_precedents case_precedents_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.case_precedents
    ADD CONSTRAINT case_precedents_pkey PRIMARY KEY (id);


--
-- Name: case_watchdog case_watchdog_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.case_watchdog
    ADD CONSTRAINT case_watchdog_pkey PRIMARY KEY (id);


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
-- Name: correspondence correspondence_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.correspondence
    ADD CONSTRAINT correspondence_pkey PRIMARY KEY (id);


--
-- Name: deadlines deadlines_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.deadlines
    ADD CONSTRAINT deadlines_pkey PRIMARY KEY (id);


--
-- Name: email_intake_queue email_intake_queue_message_uid_key; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.email_intake_queue
    ADD CONSTRAINT email_intake_queue_message_uid_key UNIQUE (message_uid);


--
-- Name: email_intake_queue email_intake_queue_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.email_intake_queue
    ADD CONSTRAINT email_intake_queue_pkey PRIMARY KEY (id);


--
-- Name: expense_intake expense_intake_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.expense_intake
    ADD CONSTRAINT expense_intake_pkey PRIMARY KEY (id);


--
-- Name: filings filings_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.filings
    ADD CONSTRAINT filings_pkey PRIMARY KEY (id);


--
-- Name: ingest_runs ingest_runs_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.ingest_runs
    ADD CONSTRAINT ingest_runs_pkey PRIMARY KEY (id);


--
-- Name: timeline_events timeline_events_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.timeline_events
    ADD CONSTRAINT timeline_events_pkey PRIMARY KEY (id);


--
-- Name: uploads uploads_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.uploads
    ADD CONSTRAINT uploads_pkey PRIMARY KEY (id);


--
-- Name: vault_documents uq_vault_documents_case_hash; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.vault_documents
    ADD CONSTRAINT uq_vault_documents_case_hash UNIQUE (case_slug, file_hash);


--
-- Name: vault_documents vault_documents_pkey; Type: CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.vault_documents
    ADD CONSTRAINT vault_documents_pkey PRIMARY KEY (id);


--
-- Name: attorney_scoring attorney_scoring_pkey; Type: CONSTRAINT; Schema: legal_cmd; Owner: -
--

ALTER TABLE ONLY legal_cmd.attorney_scoring
    ADD CONSTRAINT attorney_scoring_pkey PRIMARY KEY (id);


--
-- Name: attorneys attorneys_pkey; Type: CONSTRAINT; Schema: legal_cmd; Owner: -
--

ALTER TABLE ONLY legal_cmd.attorneys
    ADD CONSTRAINT attorneys_pkey PRIMARY KEY (id);


--
-- Name: deliberation_events deliberation_events_pkey; Type: CONSTRAINT; Schema: legal_cmd; Owner: -
--

ALTER TABLE ONLY legal_cmd.deliberation_events
    ADD CONSTRAINT deliberation_events_pkey PRIMARY KEY (event_id);


--
-- Name: deliberation_events deliberation_events_sha256_signature_key; Type: CONSTRAINT; Schema: legal_cmd; Owner: -
--

ALTER TABLE ONLY legal_cmd.deliberation_events
    ADD CONSTRAINT deliberation_events_sha256_signature_key UNIQUE (sha256_signature);


--
-- Name: documents documents_pkey; Type: CONSTRAINT; Schema: legal_cmd; Owner: -
--

ALTER TABLE ONLY legal_cmd.documents
    ADD CONSTRAINT documents_pkey PRIMARY KEY (id);


--
-- Name: matters matters_pkey; Type: CONSTRAINT; Schema: legal_cmd; Owner: -
--

ALTER TABLE ONLY legal_cmd.matters
    ADD CONSTRAINT matters_pkey PRIMARY KEY (id);


--
-- Name: matters matters_reference_code_key; Type: CONSTRAINT; Schema: legal_cmd; Owner: -
--

ALTER TABLE ONLY legal_cmd.matters
    ADD CONSTRAINT matters_reference_code_key UNIQUE (reference_code);


--
-- Name: meetings meetings_pkey; Type: CONSTRAINT; Schema: legal_cmd; Owner: -
--

ALTER TABLE ONLY legal_cmd.meetings
    ADD CONSTRAINT meetings_pkey PRIMARY KEY (id);


--
-- Name: timeline timeline_pkey; Type: CONSTRAINT; Schema: legal_cmd; Owner: -
--

ALTER TABLE ONLY legal_cmd.timeline
    ADD CONSTRAINT timeline_pkey PRIMARY KEY (id);


--
-- Name: ab_test_observations ab_test_observations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ab_test_observations
    ADD CONSTRAINT ab_test_observations_pkey PRIMARY KEY (id);


--
-- Name: ab_tests ab_tests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ab_tests
    ADD CONSTRAINT ab_tests_pkey PRIMARY KEY (id);


--
-- Name: accounts accounts_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT accounts_code_key UNIQUE (code);


--
-- Name: accounts accounts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT accounts_pkey PRIMARY KEY (id);


--
-- Name: active_learning_queue active_learning_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.active_learning_queue
    ADD CONSTRAINT active_learning_queue_pkey PRIMARY KEY (id);


--
-- Name: agent_learning_log agent_learning_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_learning_log
    ADD CONSTRAINT agent_learning_log_pkey PRIMARY KEY (id);


--
-- Name: agent_memory agent_memory_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_memory
    ADD CONSTRAINT agent_memory_pkey PRIMARY KEY (id);


--
-- Name: agent_performance_log agent_performance_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_performance_log
    ADD CONSTRAINT agent_performance_log_pkey PRIMARY KEY (id);


--
-- Name: agent_response_queue agent_response_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_response_queue
    ADD CONSTRAINT agent_response_queue_pkey PRIMARY KEY (id);


--
-- Name: agent_telemetry agent_telemetry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_telemetry
    ADD CONSTRAINT agent_telemetry_pkey PRIMARY KEY (id);


--
-- Name: ai_training_labels ai_training_labels_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_training_labels
    ADD CONSTRAINT ai_training_labels_pkey PRIMARY KEY (id);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: anomaly_flags anomaly_flags_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.anomaly_flags
    ADD CONSTRAINT anomaly_flags_pkey PRIMARY KEY (id);


--
-- Name: api_key_vault api_key_vault_key_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_key_vault
    ADD CONSTRAINT api_key_vault_key_name_key UNIQUE (key_name);


--
-- Name: api_key_vault api_key_vault_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_key_vault
    ADD CONSTRAINT api_key_vault_pkey PRIMARY KEY (id);


--
-- Name: asset_docs asset_docs_file_path_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_docs
    ADD CONSTRAINT asset_docs_file_path_key UNIQUE (file_path);


--
-- Name: asset_docs asset_docs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_docs
    ADD CONSTRAINT asset_docs_pkey PRIMARY KEY (id);


--
-- Name: conversation_threads conversation_threads_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_threads
    ADD CONSTRAINT conversation_threads_pkey PRIMARY KEY (id);


--
-- Name: conversation_threads conversation_threads_thread_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_threads
    ADD CONSTRAINT conversation_threads_thread_hash_key UNIQUE (thread_hash);


--
-- Name: council_votes council_votes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.council_votes
    ADD CONSTRAINT council_votes_pkey PRIMARY KEY (id);


--
-- Name: data_sanitizer_log data_sanitizer_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_sanitizer_log
    ADD CONSTRAINT data_sanitizer_log_pkey PRIMARY KEY (id);


--
-- Name: deferred_api_writes deferred_api_writes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deferred_api_writes
    ADD CONSTRAINT deferred_api_writes_pkey PRIMARY KEY (id);


--
-- Name: document_oracle_manifest document_oracle_manifest_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_oracle_manifest
    ADD CONSTRAINT document_oracle_manifest_pkey PRIMARY KEY (file_path);


--
-- Name: email_archive email_archive_file_path_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_archive
    ADD CONSTRAINT email_archive_file_path_key UNIQUE (file_path);


--
-- Name: email_archive email_archive_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_archive
    ADD CONSTRAINT email_archive_pkey PRIMARY KEY (id);


--
-- Name: email_classification_rules email_classification_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_classification_rules
    ADD CONSTRAINT email_classification_rules_pkey PRIMARY KEY (id);


--
-- Name: email_dead_letter_queue email_dead_letter_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_dead_letter_queue
    ADD CONSTRAINT email_dead_letter_queue_pkey PRIMARY KEY (id);


--
-- Name: email_escalation_queue email_escalation_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_escalation_queue
    ADD CONSTRAINT email_escalation_queue_pkey PRIMARY KEY (id);


--
-- Name: email_escalation_rules email_escalation_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_escalation_rules
    ADD CONSTRAINT email_escalation_rules_pkey PRIMARY KEY (id);


--
-- Name: email_intake_review_log email_intake_review_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_intake_review_log
    ADD CONSTRAINT email_intake_review_log_pkey PRIMARY KEY (id);


--
-- Name: email_quarantine email_quarantine_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_quarantine
    ADD CONSTRAINT email_quarantine_pkey PRIMARY KEY (id);


--
-- Name: email_routing_rules email_routing_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_routing_rules
    ADD CONSTRAINT email_routing_rules_pkey PRIMARY KEY (id);


--
-- Name: email_sensors email_sensors_email_address_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_sensors
    ADD CONSTRAINT email_sensors_email_address_key UNIQUE (email_address);


--
-- Name: email_sensors email_sensors_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_sensors
    ADD CONSTRAINT email_sensors_pkey PRIMARY KEY (id);


--
-- Name: email_triage_precedents email_triage_precedents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_triage_precedents
    ADD CONSTRAINT email_triage_precedents_pkey PRIMARY KEY (id);


--
-- Name: fin_owner_balances fin_owner_balances_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fin_owner_balances
    ADD CONSTRAINT fin_owner_balances_pkey PRIMARY KEY (property_id);


--
-- Name: fin_reservations fin_reservations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fin_reservations
    ADD CONSTRAINT fin_reservations_pkey PRIMARY KEY (res_id);


--
-- Name: fin_revenue_snapshots fin_revenue_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fin_revenue_snapshots
    ADD CONSTRAINT fin_revenue_snapshots_pkey PRIMARY KEY (snapshot_id);


--
-- Name: finance_invoices finance_invoices_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_invoices
    ADD CONSTRAINT finance_invoices_pkey PRIMARY KEY (id);


--
-- Name: fortress_api_keys fortress_api_keys_key_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fortress_api_keys
    ADD CONSTRAINT fortress_api_keys_key_hash_key UNIQUE (key_hash);


--
-- Name: fortress_api_keys fortress_api_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fortress_api_keys
    ADD CONSTRAINT fortress_api_keys_pkey PRIMARY KEY (id);


--
-- Name: fortress_users fortress_users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fortress_users
    ADD CONSTRAINT fortress_users_pkey PRIMARY KEY (id);


--
-- Name: fortress_users fortress_users_username_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fortress_users
    ADD CONSTRAINT fortress_users_username_key UNIQUE (username);


--
-- Name: general_ledger general_ledger_filepath_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.general_ledger
    ADD CONSTRAINT general_ledger_filepath_key UNIQUE (filepath);


--
-- Name: general_ledger general_ledger_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.general_ledger
    ADD CONSTRAINT general_ledger_pkey PRIMARY KEY (id);


--
-- Name: godhead_query_log godhead_query_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.godhead_query_log
    ADD CONSTRAINT godhead_query_log_pkey PRIMARY KEY (id);


--
-- Name: guest_leads guest_leads_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.guest_leads
    ADD CONSTRAINT guest_leads_pkey PRIMARY KEY (id);


--
-- Name: guest_profiles guest_profiles_phone_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.guest_profiles
    ADD CONSTRAINT guest_profiles_phone_number_key UNIQUE (phone_number);


--
-- Name: guest_profiles guest_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.guest_profiles
    ADD CONSTRAINT guest_profiles_pkey PRIMARY KEY (id);


--
-- Name: images images_filename_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.images
    ADD CONSTRAINT images_filename_key UNIQUE (filename);


--
-- Name: images images_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.images
    ADD CONSTRAINT images_pkey PRIMARY KEY (id);


--
-- Name: ingestion_dlq ingestion_dlq_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ingestion_dlq
    ADD CONSTRAINT ingestion_dlq_pkey PRIMARY KEY (id);


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
-- Name: learning_judgments learning_judgments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learning_judgments
    ADD CONSTRAINT learning_judgments_pkey PRIMARY KEY (id);


--
-- Name: learning_optimizations learning_optimizations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learning_optimizations
    ADD CONSTRAINT learning_optimizations_pkey PRIMARY KEY (id);


--
-- Name: legacy_cdc_checkpoints legacy_cdc_checkpoints_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legacy_cdc_checkpoints
    ADD CONSTRAINT legacy_cdc_checkpoints_pkey PRIMARY KEY (stream_name);


--
-- Name: legacy_cdc_event_queue legacy_cdc_event_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legacy_cdc_event_queue
    ADD CONSTRAINT legacy_cdc_event_queue_pkey PRIMARY KEY (id);


--
-- Name: legacy_cdc_row_state legacy_cdc_row_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legacy_cdc_row_state
    ADD CONSTRAINT legacy_cdc_row_state_pkey PRIMARY KEY (source_table, primary_key_hash);


--
-- Name: legal_clients legal_clients_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legal_clients
    ADD CONSTRAINT legal_clients_pkey PRIMARY KEY (client_id);


--
-- Name: legal_docket legal_docket_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legal_docket
    ADD CONSTRAINT legal_docket_pkey PRIMARY KEY (doc_id);


--
-- Name: legal_intel legal_intel_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legal_intel
    ADD CONSTRAINT legal_intel_pkey PRIMARY KEY (id);


--
-- Name: legal_matter_notes legal_matter_notes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legal_matter_notes
    ADD CONSTRAINT legal_matter_notes_pkey PRIMARY KEY (note_id);


--
-- Name: legal_matters legal_matters_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legal_matters
    ADD CONSTRAINT legal_matters_pkey PRIMARY KEY (matter_id);


--
-- Name: maintenance_log maintenance_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_log
    ADD CONSTRAINT maintenance_log_pkey PRIMARY KEY (id);


--
-- Name: market_intel market_intel_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.market_intel
    ADD CONSTRAINT market_intel_pkey PRIMARY KEY (id);


--
-- Name: market_signals market_signals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.market_signals
    ADD CONSTRAINT market_signals_pkey PRIMARY KEY (id);


--
-- Name: message_analytics message_analytics_date_hour_property_id_source_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_analytics
    ADD CONSTRAINT message_analytics_date_hour_property_id_source_key UNIQUE (date, hour, property_id, source);


--
-- Name: message_analytics message_analytics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_analytics
    ADD CONSTRAINT message_analytics_pkey PRIMARY KEY (id);


--
-- Name: message_archive message_archive_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_archive
    ADD CONSTRAINT message_archive_pkey PRIMARY KEY (id);


--
-- Name: model_telemetry model_telemetry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_telemetry
    ADD CONSTRAINT model_telemetry_pkey PRIMARY KEY (id);


--
-- Name: nas_legal_vault nas_legal_vault_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nas_legal_vault
    ADD CONSTRAINT nas_legal_vault_pkey PRIMARY KEY (id);


--
-- Name: nas_legal_vault nas_legal_vault_source_file_chunk_index_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nas_legal_vault
    ADD CONSTRAINT nas_legal_vault_source_file_chunk_index_key UNIQUE (source_file, chunk_index);


--
-- Name: nim_arm64_probe_results nim_arm64_probe_results_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nim_arm64_probe_results
    ADD CONSTRAINT nim_arm64_probe_results_pkey PRIMARY KEY (id);


--
-- Name: nim_arm64_probe_results nim_arm64_probe_results_probe_date_image_path_tag_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nim_arm64_probe_results
    ADD CONSTRAINT nim_arm64_probe_results_probe_date_image_path_tag_key UNIQUE (probe_date, image_path, tag);


--
-- Name: ops_crew ops_crew_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ops_crew
    ADD CONSTRAINT ops_crew_pkey PRIMARY KEY (id);


--
-- Name: ops_historical_guests ops_historical_guests_guest_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ops_historical_guests
    ADD CONSTRAINT ops_historical_guests_guest_id_key UNIQUE (guest_id);


--
-- Name: ops_historical_guests ops_historical_guests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ops_historical_guests
    ADD CONSTRAINT ops_historical_guests_pkey PRIMARY KEY (id);


--
-- Name: ops_log ops_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ops_log
    ADD CONSTRAINT ops_log_pkey PRIMARY KEY (id);


--
-- Name: ops_overrides ops_overrides_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ops_overrides
    ADD CONSTRAINT ops_overrides_pkey PRIMARY KEY (id);


--
-- Name: ops_properties ops_properties_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ops_properties
    ADD CONSTRAINT ops_properties_pkey PRIMARY KEY (property_id);


--
-- Name: ops_properties ops_properties_streamline_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ops_properties
    ADD CONSTRAINT ops_properties_streamline_id_key UNIQUE (streamline_id);


--
-- Name: ops_tasks ops_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ops_tasks
    ADD CONSTRAINT ops_tasks_pkey PRIMARY KEY (id);


--
-- Name: ops_turnovers ops_turnovers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ops_turnovers
    ADD CONSTRAINT ops_turnovers_pkey PRIMARY KEY (id);


--
-- Name: ops_visuals ops_visuals_file_path_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ops_visuals
    ADD CONSTRAINT ops_visuals_file_path_key UNIQUE (file_path);


--
-- Name: ops_visuals ops_visuals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ops_visuals
    ADD CONSTRAINT ops_visuals_pkey PRIMARY KEY (image_id);


--
-- Name: pages pages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pages
    ADD CONSTRAINT pages_pkey PRIMARY KEY (id);


--
-- Name: pages pages_url_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pages
    ADD CONSTRAINT pages_url_key UNIQUE (url);


--
-- Name: persona_scores persona_scores_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persona_scores
    ADD CONSTRAINT persona_scores_pkey PRIMARY KEY (persona_slug);


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
-- Name: properties properties_streamline_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.properties
    ADD CONSTRAINT properties_streamline_id_key UNIQUE (streamline_id);


--
-- Name: property_events property_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.property_events
    ADD CONSTRAINT property_events_pkey PRIMARY KEY (id);


--
-- Name: property_sms_config property_sms_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.property_sms_config
    ADD CONSTRAINT property_sms_config_pkey PRIMARY KEY (id);


--
-- Name: property_sms_config property_sms_config_property_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.property_sms_config
    ADD CONSTRAINT property_sms_config_property_id_key UNIQUE (property_id);


--
-- Name: quarantine_inbox quarantine_inbox_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quarantine_inbox
    ADD CONSTRAINT quarantine_inbox_pkey PRIMARY KEY (id);


--
-- Name: rag_query_feedback rag_query_feedback_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rag_query_feedback
    ADD CONSTRAINT rag_query_feedback_pkey PRIMARY KEY (id);


--
-- Name: real_estate_intel real_estate_intel_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.real_estate_intel
    ADD CONSTRAINT real_estate_intel_pkey PRIMARY KEY (id);


--
-- Name: recursive_trace_log recursive_trace_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recursive_trace_log
    ADD CONSTRAINT recursive_trace_log_pkey PRIMARY KEY (id);


--
-- Name: revenue_ledger revenue_ledger_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.revenue_ledger
    ADD CONSTRAINT revenue_ledger_pkey PRIMARY KEY (id);


--
-- Name: ruebarue_area_guide ruebarue_area_guide_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ruebarue_area_guide
    ADD CONSTRAINT ruebarue_area_guide_pkey PRIMARY KEY (id);


--
-- Name: ruebarue_contacts ruebarue_contacts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ruebarue_contacts
    ADD CONSTRAINT ruebarue_contacts_pkey PRIMARY KEY (id);


--
-- Name: ruebarue_guests ruebarue_guests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ruebarue_guests
    ADD CONSTRAINT ruebarue_guests_pkey PRIMARY KEY (id);


--
-- Name: ruebarue_knowledge_base ruebarue_knowledge_base_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ruebarue_knowledge_base
    ADD CONSTRAINT ruebarue_knowledge_base_pkey PRIMARY KEY (id);


--
-- Name: ruebarue_message_templates ruebarue_message_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ruebarue_message_templates
    ADD CONSTRAINT ruebarue_message_templates_pkey PRIMARY KEY (id);


--
-- Name: sales_intel sales_intel_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sales_intel
    ADD CONSTRAINT sales_intel_pkey PRIMARY KEY (id);


--
-- Name: schema_drift_log schema_drift_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_drift_log
    ADD CONSTRAINT schema_drift_log_pkey PRIMARY KEY (id);


--
-- Name: sender_registry sender_registry_raw_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sender_registry
    ADD CONSTRAINT sender_registry_raw_unique UNIQUE (sender_raw);


--
-- Name: sentinel_alerts sentinel_alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sentinel_alerts
    ADD CONSTRAINT sentinel_alerts_pkey PRIMARY KEY (id);


--
-- Name: sentinel_state sentinel_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sentinel_state
    ADD CONSTRAINT sentinel_state_pkey PRIMARY KEY (key);


--
-- Name: sms_providers sms_providers_name_account_sid_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sms_providers
    ADD CONSTRAINT sms_providers_name_account_sid_key UNIQUE (name, account_sid);


--
-- Name: sms_providers sms_providers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sms_providers
    ADD CONSTRAINT sms_providers_pkey PRIMARY KEY (id);


--
-- Name: sovereign_cycles sovereign_cycles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sovereign_cycles
    ADD CONSTRAINT sovereign_cycles_pkey PRIMARY KEY (id);


--
-- Name: starred_responses starred_responses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.starred_responses
    ADD CONSTRAINT starred_responses_pkey PRIMARY KEY (id);


--
-- Name: sys_api_credentials sys_api_credentials_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sys_api_credentials
    ADD CONSTRAINT sys_api_credentials_pkey PRIMARY KEY (service_name);


--
-- Name: system_directives system_directives_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_directives
    ADD CONSTRAINT system_directives_pkey PRIMARY KEY (id);


--
-- Name: system_drift_alerts system_drift_alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_drift_alerts
    ADD CONSTRAINT system_drift_alerts_pkey PRIMARY KEY (id);


--
-- Name: system_post_mortems system_post_mortems_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_post_mortems
    ADD CONSTRAINT system_post_mortems_pkey PRIMARY KEY (id);


--
-- Name: system_telemetry system_telemetry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_telemetry
    ADD CONSTRAINT system_telemetry_pkey PRIMARY KEY (id);


--
-- Name: trust_balance trust_balance_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trust_balance
    ADD CONSTRAINT trust_balance_pkey PRIMARY KEY (id);


--
-- Name: trust_balance uq_trust_property; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trust_balance
    ADD CONSTRAINT uq_trust_property UNIQUE (property_id);


--
-- Name: vault_alpha_state_law vault_alpha_state_law_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_alpha_state_law
    ADD CONSTRAINT vault_alpha_state_law_pkey PRIMARY KEY (id);


--
-- Name: vault_beta_federal_law vault_beta_federal_law_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_beta_federal_law
    ADD CONSTRAINT vault_beta_federal_law_pkey PRIMARY KEY (id);


--
-- Name: vault_delta vault_delta_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_delta
    ADD CONSTRAINT vault_delta_pkey PRIMARY KEY (id);


--
-- Name: vault_gamma_evidence vault_gamma_evidence_file_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_gamma_evidence
    ADD CONSTRAINT vault_gamma_evidence_file_hash_key UNIQUE (file_hash);


--
-- Name: vault_gamma_evidence vault_gamma_evidence_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_gamma_evidence
    ADD CONSTRAINT vault_gamma_evidence_pkey PRIMARY KEY (id);


--
-- Name: vision_runs vision_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vision_runs
    ADD CONSTRAINT vision_runs_pkey PRIMARY KEY (run_id);


--
-- Name: idx_div_a_pred_metric; Type: INDEX; Schema: division_a; Owner: -
--

CREATE INDEX idx_div_a_pred_metric ON division_a.predictions USING btree (metric_name);


--
-- Name: idx_div_a_txn_category; Type: INDEX; Schema: division_a; Owner: -
--

CREATE INDEX idx_div_a_txn_category ON division_a.transactions USING btree (category);


--
-- Name: idx_div_a_txn_date; Type: INDEX; Schema: division_a; Owner: -
--

CREATE INDEX idx_div_a_txn_date ON division_a.transactions USING btree (date);


--
-- Name: idx_div_a_txn_vendor; Type: INDEX; Schema: division_a; Owner: -
--

CREATE INDEX idx_div_a_txn_vendor ON division_a.transactions USING btree (vendor);


--
-- Name: idx_division_a_am_vendor; Type: INDEX; Schema: division_a; Owner: -
--

CREATE INDEX idx_division_a_am_vendor ON division_a.account_mappings USING btree (vendor_name);


--
-- Name: idx_division_a_coa_type; Type: INDEX; Schema: division_a; Owner: -
--

CREATE INDEX idx_division_a_coa_type ON division_a.chart_of_accounts USING btree (account_type);


--
-- Name: idx_division_a_gl_account; Type: INDEX; Schema: division_a; Owner: -
--

CREATE INDEX idx_division_a_gl_account ON division_a.general_ledger USING btree (account_code);


--
-- Name: idx_division_a_gl_date; Type: INDEX; Schema: division_a; Owner: -
--

CREATE INDEX idx_division_a_gl_date ON division_a.general_ledger USING btree (created_at);


--
-- Name: idx_division_a_gl_entry; Type: INDEX; Schema: division_a; Owner: -
--

CREATE INDEX idx_division_a_gl_entry ON division_a.general_ledger USING btree (journal_entry_id);


--
-- Name: idx_division_a_je_date; Type: INDEX; Schema: division_a; Owner: -
--

CREATE INDEX idx_division_a_je_date ON division_a.journal_entries USING btree (entry_date);


--
-- Name: idx_division_a_je_source; Type: INDEX; Schema: division_a; Owner: -
--

CREATE INDEX idx_division_a_je_source ON division_a.journal_entries USING btree (source_ref);


--
-- Name: idx_div_b_escrow_cabin; Type: INDEX; Schema: division_b; Owner: -
--

CREATE INDEX idx_div_b_escrow_cabin ON division_b.escrow USING btree (cabin_id);


--
-- Name: idx_div_b_escrow_status; Type: INDEX; Schema: division_b; Owner: -
--

CREATE INDEX idx_div_b_escrow_status ON division_b.escrow USING btree (status);


--
-- Name: idx_div_b_txn_date; Type: INDEX; Schema: division_b; Owner: -
--

CREATE INDEX idx_div_b_txn_date ON division_b.transactions USING btree (date);


--
-- Name: idx_div_b_txn_trust; Type: INDEX; Schema: division_b; Owner: -
--

CREATE INDEX idx_div_b_txn_trust ON division_b.transactions USING btree (trust_related);


--
-- Name: idx_division_b_am_vendor; Type: INDEX; Schema: division_b; Owner: -
--

CREATE INDEX idx_division_b_am_vendor ON division_b.account_mappings USING btree (vendor_name);


--
-- Name: idx_division_b_coa_type; Type: INDEX; Schema: division_b; Owner: -
--

CREATE INDEX idx_division_b_coa_type ON division_b.chart_of_accounts USING btree (account_type);


--
-- Name: idx_division_b_gl_account; Type: INDEX; Schema: division_b; Owner: -
--

CREATE INDEX idx_division_b_gl_account ON division_b.general_ledger USING btree (account_code);


--
-- Name: idx_division_b_gl_date; Type: INDEX; Schema: division_b; Owner: -
--

CREATE INDEX idx_division_b_gl_date ON division_b.general_ledger USING btree (created_at);


--
-- Name: idx_division_b_gl_entry; Type: INDEX; Schema: division_b; Owner: -
--

CREATE INDEX idx_division_b_gl_entry ON division_b.general_ledger USING btree (journal_entry_id);


--
-- Name: idx_division_b_je_date; Type: INDEX; Schema: division_b; Owner: -
--

CREATE INDEX idx_division_b_je_date ON division_b.journal_entries USING btree (entry_date);


--
-- Name: idx_division_b_je_source; Type: INDEX; Schema: division_b; Owner: -
--

CREATE INDEX idx_division_b_je_source ON division_b.journal_entries USING btree (source_ref);


--
-- Name: idx_eng_co_project; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_co_project ON engineering.change_orders USING btree (project_id);


--
-- Name: idx_eng_co_status; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_co_status ON engineering.change_orders USING btree (status);


--
-- Name: idx_eng_comp_project; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_comp_project ON engineering.compliance_log USING btree (project_id);


--
-- Name: idx_eng_comp_severity; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_comp_severity ON engineering.compliance_log USING btree (severity);


--
-- Name: idx_eng_comp_status; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_comp_status ON engineering.compliance_log USING btree (status);


--
-- Name: idx_eng_cost_project; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_cost_project ON engineering.cost_estimates USING btree (project_id);


--
-- Name: idx_eng_cost_type; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_cost_type ON engineering.cost_estimates USING btree (estimate_type);


--
-- Name: idx_eng_draw_discipline; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_draw_discipline ON engineering.drawings USING btree (discipline);


--
-- Name: idx_eng_draw_doc_type; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_draw_doc_type ON engineering.drawings USING btree (doc_type);


--
-- Name: idx_eng_draw_project; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_draw_project ON engineering.drawings USING btree (project_id);


--
-- Name: idx_eng_draw_property; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_draw_property ON engineering.drawings USING btree (property_id);


--
-- Name: idx_eng_insp_project; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_insp_project ON engineering.inspections USING btree (project_id);


--
-- Name: idx_eng_insp_result; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_insp_result ON engineering.inspections USING btree (result);


--
-- Name: idx_eng_insp_scheduled; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_insp_scheduled ON engineering.inspections USING btree (scheduled_date);


--
-- Name: idx_eng_mep_condition; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_mep_condition ON engineering.mep_systems USING btree (condition);


--
-- Name: idx_eng_mep_property; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_mep_property ON engineering.mep_systems USING btree (property_id);


--
-- Name: idx_eng_mep_type; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_mep_type ON engineering.mep_systems USING btree (system_type);


--
-- Name: idx_eng_perm_expiration; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_perm_expiration ON engineering.permits USING btree (expiration_date);


--
-- Name: idx_eng_perm_project; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_perm_project ON engineering.permits USING btree (project_id);


--
-- Name: idx_eng_perm_status; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_perm_status ON engineering.permits USING btree (status);


--
-- Name: idx_eng_proj_phase; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_proj_phase ON engineering.projects USING btree (phase);


--
-- Name: idx_eng_proj_property; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_proj_property ON engineering.projects USING btree (property_id);


--
-- Name: idx_eng_proj_status; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_proj_status ON engineering.projects USING btree (status);


--
-- Name: idx_eng_punch_project; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_punch_project ON engineering.punch_items USING btree (project_id);


--
-- Name: idx_eng_punch_status; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_punch_status ON engineering.punch_items USING btree (status);


--
-- Name: idx_eng_rfi_project; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_rfi_project ON engineering.rfis USING btree (project_id);


--
-- Name: idx_eng_rfi_status; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_rfi_status ON engineering.rfis USING btree (status);


--
-- Name: idx_eng_sub_project; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_sub_project ON engineering.submittals USING btree (project_id);


--
-- Name: idx_eng_sub_status; Type: INDEX; Schema: engineering; Owner: -
--

CREATE INDEX idx_eng_sub_status ON engineering.submittals USING btree (status);


--
-- Name: idx_classification_rules_embedding_hnsw; Type: INDEX; Schema: finance; Owner: -
--

CREATE INDEX idx_classification_rules_embedding_hnsw ON finance.classification_rules USING hnsw (embedding public.vector_cosine_ops) WITH (m='16', ef_construction='64');


--
-- Name: idx_rules_category; Type: INDEX; Schema: finance; Owner: -
--

CREATE INDEX idx_rules_category ON finance.classification_rules USING btree (assigned_category);


--
-- Name: idx_rules_embedding_hnsw; Type: INDEX; Schema: finance; Owner: -
--

CREATE INDEX idx_rules_embedding_hnsw ON finance.classification_rules USING hnsw (embedding public.vector_cosine_ops) WITH (m='16', ef_construction='64');


--
-- Name: idx_vendor_class_pattern; Type: INDEX; Schema: finance; Owner: -
--

CREATE INDEX idx_vendor_class_pattern ON finance.vendor_classifications USING btree (vendor_pattern);


--
-- Name: idx_hf_extraction_email_unique; Type: INDEX; Schema: hedge_fund; Owner: -
--

CREATE UNIQUE INDEX idx_hf_extraction_email_unique ON hedge_fund.extraction_log USING btree (email_id);


--
-- Name: idx_hf_signals_action; Type: INDEX; Schema: hedge_fund; Owner: -
--

CREATE INDEX idx_hf_signals_action ON hedge_fund.market_signals USING btree (action);


--
-- Name: idx_hf_signals_confidence; Type: INDEX; Schema: hedge_fund; Owner: -
--

CREATE INDEX idx_hf_signals_confidence ON hedge_fund.market_signals USING btree (confidence_score);


--
-- Name: idx_hf_signals_extracted; Type: INDEX; Schema: hedge_fund; Owner: -
--

CREATE INDEX idx_hf_signals_extracted ON hedge_fund.market_signals USING btree (extracted_at);


--
-- Name: idx_hf_signals_ticker; Type: INDEX; Schema: hedge_fund; Owner: -
--

CREATE INDEX idx_hf_signals_ticker ON hedge_fund.market_signals USING btree (ticker);


--
-- Name: idx_hf_watchlist_ticker; Type: INDEX; Schema: hedge_fund; Owner: -
--

CREATE INDEX idx_hf_watchlist_ticker ON hedge_fund.watchlist USING btree (ticker);


--
-- Name: idx_entities_key; Type: INDEX; Schema: intelligence; Owner: -
--

CREATE INDEX idx_entities_key ON intelligence.entities USING btree (entity_key);


--
-- Name: idx_entities_type; Type: INDEX; Schema: intelligence; Owner: -
--

CREATE INDEX idx_entities_type ON intelligence.entities USING btree (entity_type);


--
-- Name: idx_golden_entity; Type: INDEX; Schema: intelligence; Owner: -
--

CREATE INDEX idx_golden_entity ON intelligence.golden_reasoning USING btree (entity_key);


--
-- Name: idx_golden_topic; Type: INDEX; Schema: intelligence; Owner: -
--

CREATE INDEX idx_golden_topic ON intelligence.golden_reasoning USING btree (topic);


--
-- Name: idx_rel_from; Type: INDEX; Schema: intelligence; Owner: -
--

CREATE INDEX idx_rel_from ON intelligence.relationships USING btree (from_entity_id);


--
-- Name: idx_rel_to; Type: INDEX; Schema: intelligence; Owner: -
--

CREATE INDEX idx_rel_to ON intelligence.relationships USING btree (to_entity_id);


--
-- Name: idx_rel_type; Type: INDEX; Schema: intelligence; Owner: -
--

CREATE INDEX idx_rel_type ON intelligence.relationships USING btree (relationship_type);


--
-- Name: idx_traces_created; Type: INDEX; Schema: intelligence; Owner: -
--

CREATE INDEX idx_traces_created ON intelligence.titan_traces USING btree (created_at DESC);


--
-- Name: idx_traces_session; Type: INDEX; Schema: intelligence; Owner: -
--

CREATE INDEX idx_traces_session ON intelligence.titan_traces USING btree (session_type);


--
-- Name: idx_case_actions_case; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_case_actions_case ON legal.case_actions USING btree (case_id);


--
-- Name: idx_case_evidence_case; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_case_evidence_case ON legal.case_evidence USING btree (case_id);


--
-- Name: idx_case_precedents_score; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_case_precedents_score ON legal.case_precedents USING btree (relevance_score DESC);


--
-- Name: idx_case_precedents_slug; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_case_precedents_slug ON legal.case_precedents USING btree (case_slug);


--
-- Name: idx_case_slug; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_case_slug ON legal.cases USING btree (case_slug);


--
-- Name: idx_case_watchdog_case; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_case_watchdog_case ON legal.case_watchdog USING btree (case_id);


--
-- Name: idx_correspondence_case; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_correspondence_case ON legal.correspondence USING btree (case_id);


--
-- Name: idx_correspondence_status; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_correspondence_status ON legal.correspondence USING btree (status);


--
-- Name: idx_deadlines_case; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_deadlines_case ON legal.deadlines USING btree (case_id);


--
-- Name: idx_deadlines_due; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_deadlines_due ON legal.deadlines USING btree (due_date);


--
-- Name: idx_deadlines_status; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_deadlines_status ON legal.deadlines USING btree (status);


--
-- Name: idx_filings_case; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_filings_case ON legal.filings USING btree (case_id);


--
-- Name: idx_ingest_runs_case_slug; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_ingest_runs_case_slug ON legal.ingest_runs USING btree (case_slug);


--
-- Name: idx_ingest_runs_started_at; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_ingest_runs_started_at ON legal.ingest_runs USING btree (started_at DESC);


--
-- Name: idx_ingest_runs_status; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_ingest_runs_status ON legal.ingest_runs USING btree (status) WHERE (status = ANY (ARRAY['running'::text, 'error'::text]));


--
-- Name: idx_legalexp_case; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_legalexp_case ON legal.expense_intake USING btree (case_slug);


--
-- Name: idx_uploads_case; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_uploads_case ON legal.uploads USING btree (case_id);


--
-- Name: idx_uploads_filing; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_uploads_filing ON legal.uploads USING btree (filing_id);


--
-- Name: idx_vault_documents_case_slug; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_vault_documents_case_slug ON legal.vault_documents USING btree (case_slug);


--
-- Name: idx_vault_documents_created_at; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_vault_documents_created_at ON legal.vault_documents USING btree (created_at DESC);


--
-- Name: idx_vault_documents_file_hash; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_vault_documents_file_hash ON legal.vault_documents USING btree (file_hash);


--
-- Name: idx_vault_documents_status; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX idx_vault_documents_status ON legal.vault_documents USING btree (processing_status) WHERE (processing_status = ANY (ARRAY['pending'::text, 'processing'::text, 'vectorizing'::text, 'error'::text, 'failed'::text, 'ocr_failed'::text]));


--
-- Name: ix_legal_email_intake_case; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_email_intake_case ON legal.email_intake_queue USING btree (case_slug);


--
-- Name: ix_legal_email_intake_rcvd; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_email_intake_rcvd ON legal.email_intake_queue USING btree (received_at DESC);


--
-- Name: ix_legal_email_intake_status; Type: INDEX; Schema: legal; Owner: -
--

CREATE INDEX ix_legal_email_intake_status ON legal.email_intake_queue USING btree (intake_status);


--
-- Name: uq_deadlines_content_hash; Type: INDEX; Schema: legal; Owner: -
--

CREATE UNIQUE INDEX uq_deadlines_content_hash ON legal.deadlines USING btree (content_hash) WHERE (content_hash IS NOT NULL);


--
-- Name: idx_attorney_score; Type: INDEX; Schema: legal_cmd; Owner: -
--

CREATE INDEX idx_attorney_score ON legal_cmd.attorney_scoring USING btree (sota_match_score DESC);


--
-- Name: idx_attorneys_ai_score; Type: INDEX; Schema: legal_cmd; Owner: -
--

CREATE INDEX idx_attorneys_ai_score ON legal_cmd.attorneys USING btree (ai_score DESC);


--
-- Name: idx_attorneys_outreach; Type: INDEX; Schema: legal_cmd; Owner: -
--

CREATE INDEX idx_attorneys_outreach ON legal_cmd.attorneys USING btree (outreach_status);


--
-- Name: idx_attorneys_practice; Type: INDEX; Schema: legal_cmd; Owner: -
--

CREATE INDEX idx_attorneys_practice ON legal_cmd.attorneys USING gin (practice_areas);


--
-- Name: idx_attorneys_specialty; Type: INDEX; Schema: legal_cmd; Owner: -
--

CREATE INDEX idx_attorneys_specialty ON legal_cmd.attorneys USING btree (specialty);


--
-- Name: idx_attorneys_status; Type: INDEX; Schema: legal_cmd; Owner: -
--

CREATE INDEX idx_attorneys_status ON legal_cmd.attorneys USING btree (status);


--
-- Name: idx_delib_case; Type: INDEX; Schema: legal_cmd; Owner: -
--

CREATE INDEX idx_delib_case ON legal_cmd.deliberation_events USING btree (case_slug, "timestamp" DESC);


--
-- Name: idx_delib_sig; Type: INDEX; Schema: legal_cmd; Owner: -
--

CREATE INDEX idx_delib_sig ON legal_cmd.deliberation_events USING btree (sha256_signature);


--
-- Name: idx_documents_matter; Type: INDEX; Schema: legal_cmd; Owner: -
--

CREATE INDEX idx_documents_matter ON legal_cmd.documents USING btree (matter_id);


--
-- Name: idx_documents_type; Type: INDEX; Schema: legal_cmd; Owner: -
--

CREATE INDEX idx_documents_type ON legal_cmd.documents USING btree (doc_type);


--
-- Name: idx_matters_attorney; Type: INDEX; Schema: legal_cmd; Owner: -
--

CREATE INDEX idx_matters_attorney ON legal_cmd.matters USING btree (attorney_id);


--
-- Name: idx_matters_category; Type: INDEX; Schema: legal_cmd; Owner: -
--

CREATE INDEX idx_matters_category ON legal_cmd.matters USING btree (category);


--
-- Name: idx_matters_priority; Type: INDEX; Schema: legal_cmd; Owner: -
--

CREATE INDEX idx_matters_priority ON legal_cmd.matters USING btree (priority);


--
-- Name: idx_matters_status; Type: INDEX; Schema: legal_cmd; Owner: -
--

CREATE INDEX idx_matters_status ON legal_cmd.matters USING btree (status);


--
-- Name: idx_meetings_attorney; Type: INDEX; Schema: legal_cmd; Owner: -
--

CREATE INDEX idx_meetings_attorney ON legal_cmd.meetings USING btree (attorney_id);


--
-- Name: idx_meetings_date; Type: INDEX; Schema: legal_cmd; Owner: -
--

CREATE INDEX idx_meetings_date ON legal_cmd.meetings USING btree (meeting_date);


--
-- Name: idx_meetings_matter; Type: INDEX; Schema: legal_cmd; Owner: -
--

CREATE INDEX idx_meetings_matter ON legal_cmd.meetings USING btree (matter_id);


--
-- Name: idx_timeline_created; Type: INDEX; Schema: legal_cmd; Owner: -
--

CREATE INDEX idx_timeline_created ON legal_cmd.timeline USING btree (created_at);


--
-- Name: idx_timeline_matter; Type: INDEX; Schema: legal_cmd; Owner: -
--

CREATE INDEX idx_timeline_matter ON legal_cmd.timeline USING btree (matter_id);


--
-- Name: idx_timeline_type; Type: INDEX; Schema: legal_cmd; Owner: -
--

CREATE INDEX idx_timeline_type ON legal_cmd.timeline USING btree (entry_type);


--
-- Name: alpha_gin_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX alpha_gin_idx ON public.vault_alpha_state_law USING gin (text_search);


--
-- Name: alpha_meta_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX alpha_meta_idx ON public.vault_alpha_state_law USING gin (metadata);


--
-- Name: alpha_state_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX alpha_state_idx ON public.vault_alpha_state_law USING gin (text_search);


--
-- Name: beta_federal_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX beta_federal_idx ON public.vault_beta_federal_law USING gin (text_search);


--
-- Name: beta_gin_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX beta_gin_idx ON public.vault_beta_federal_law USING gin (text_search);


--
-- Name: beta_meta_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX beta_meta_idx ON public.vault_beta_federal_law USING gin (metadata);


--
-- Name: council_log_session_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX council_log_session_idx ON public.godhead_query_log USING btree (session_id);


--
-- Name: council_log_time_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX council_log_time_idx ON public.godhead_query_log USING btree (queried_at DESC);


--
-- Name: gamma_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX gamma_date_idx ON public.vault_gamma_evidence USING btree (date_authored);


--
-- Name: gamma_hash_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX gamma_hash_idx ON public.vault_gamma_evidence USING btree (file_hash);


--
-- Name: gamma_metadata_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX gamma_metadata_idx ON public.vault_gamma_evidence USING gin (metadata);


--
-- Name: gamma_text_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX gamma_text_idx ON public.vault_gamma_evidence USING gin (text_search);


--
-- Name: gamma_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX gamma_type_idx ON public.vault_gamma_evidence USING btree (doc_type);


--
-- Name: idx_ab_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ab_agent ON public.ab_tests USING btree (agent_id);


--
-- Name: idx_ab_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ab_status ON public.ab_tests USING btree (status);


--
-- Name: idx_abo_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_abo_created ON public.ab_test_observations USING btree (created_at);


--
-- Name: idx_abo_test; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_abo_test ON public.ab_test_observations USING btree (test_id);


--
-- Name: idx_abo_variant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_abo_variant ON public.ab_test_observations USING btree (variant);


--
-- Name: idx_acct_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_acct_code ON public.accounts USING btree (code);


--
-- Name: idx_acct_property; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_acct_property ON public.accounts USING btree (property_id);


--
-- Name: idx_acct_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_acct_type ON public.accounts USING btree (account_type);


--
-- Name: idx_ad_doc_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ad_doc_type ON public.asset_docs USING btree (doc_type);


--
-- Name: idx_ad_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ad_property_id ON public.asset_docs USING btree (property_id);


--
-- Name: idx_ad_property_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ad_property_name ON public.asset_docs USING btree (property_name);


--
-- Name: idx_af_entry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_af_entry ON public.anomaly_flags USING btree (journal_entry_id);


--
-- Name: idx_af_reviewed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_af_reviewed ON public.anomaly_flags USING btree (reviewed);


--
-- Name: idx_af_severity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_af_severity ON public.anomaly_flags USING btree (severity);


--
-- Name: idx_af_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_af_type ON public.anomaly_flags USING btree (flag_type);


--
-- Name: idx_agent_memory_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_memory_created_at ON public.agent_memory USING btree (created_at);


--
-- Name: idx_agent_telemetry_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_telemetry_created_at ON public.agent_telemetry USING btree (created_at);


--
-- Name: idx_agent_telemetry_success; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_telemetry_success ON public.agent_telemetry USING btree (error_class) WHERE (error_class IS NULL);


--
-- Name: idx_alq_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_alq_agent ON public.active_learning_queue USING btree (agent_id);


--
-- Name: idx_alq_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_alq_status ON public.active_learning_queue USING btree (status);


--
-- Name: idx_analytics_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_analytics_date ON public.message_analytics USING btree (date DESC);


--
-- Name: idx_analytics_property; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_analytics_property ON public.message_analytics USING btree (property_id);


--
-- Name: idx_apl_date; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_apl_date ON public.agent_performance_log USING btree (date);


--
-- Name: idx_arq_cabin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_arq_cabin ON public.agent_response_queue USING btree (cabin_name);


--
-- Name: idx_arq_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_arq_created ON public.agent_response_queue USING btree (created_at DESC);


--
-- Name: idx_arq_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_arq_status ON public.agent_response_queue USING btree (status);


--
-- Name: idx_arq_urgency; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_arq_urgency ON public.agent_response_queue USING btree (urgency_level DESC);


--
-- Name: idx_class_rules_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_class_rules_active ON public.email_classification_rules USING btree (division, is_active) WHERE (is_active = true);


--
-- Name: idx_council_votes_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_council_votes_created ON public.council_votes USING btree (created_at DESC);


--
-- Name: idx_council_votes_resolved; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_council_votes_resolved ON public.council_votes USING btree (resolved_at) WHERE (resolved_at IS NOT NULL);


--
-- Name: idx_deferred_writes_service; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_deferred_writes_service ON public.deferred_api_writes USING btree (service, method);


--
-- Name: idx_deferred_writes_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_deferred_writes_status ON public.deferred_api_writes USING btree (status, next_retry_at);


--
-- Name: idx_dlq_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dlq_created ON public.ingestion_dlq USING btree (created_at DESC);


--
-- Name: idx_dlq_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dlq_source ON public.ingestion_dlq USING btree (source, resolved);


--
-- Name: idx_dlq_status_retry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dlq_status_retry ON public.email_dead_letter_queue USING btree (status, next_retry_at);


--
-- Name: idx_docket_matter; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_docket_matter ON public.legal_docket USING btree (matter_id);


--
-- Name: idx_drift_endpoint; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_drift_endpoint ON public.schema_drift_log USING btree (endpoint, created_at DESC);


--
-- Name: idx_email_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_email_category ON public.email_archive USING btree (category);


--
-- Name: idx_email_division; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_email_division ON public.email_archive USING btree (division);


--
-- Name: idx_email_division_null; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_email_division_null ON public.email_archive USING btree (id) WHERE (division IS NULL);


--
-- Name: idx_email_ingested_from; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_email_ingested_from ON public.email_archive USING btree (ingested_from);


--
-- Name: idx_email_message_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_email_message_id ON public.email_archive USING btree (message_id);


--
-- Name: idx_email_mined; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_email_mined ON public.email_archive USING btree (is_mined);


--
-- Name: idx_email_to_addr; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_email_to_addr ON public.email_archive USING btree (to_addresses);


--
-- Name: idx_email_triage_precedents_embedding_hnsw; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_email_triage_precedents_embedding_hnsw ON public.email_triage_precedents USING hnsw (embedding public.vector_cosine_ops) WITH (m='16', ef_construction='64');


--
-- Name: idx_email_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_email_ts ON public.email_archive USING gin (ts);


--
-- Name: idx_escalation_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_escalation_pending ON public.email_escalation_queue USING btree (status, priority) WHERE ((status)::text = 'pending'::text);


--
-- Name: idx_etp_division; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_etp_division ON public.email_triage_precedents USING btree (division);


--
-- Name: idx_etp_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_etp_embedding ON public.email_triage_precedents USING hnsw (embedding public.vector_cosine_ops);


--
-- Name: idx_fin_res_dates; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fin_res_dates ON public.fin_reservations USING btree (check_in, check_out);


--
-- Name: idx_fin_res_property; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fin_res_property ON public.fin_reservations USING btree (property_id);


--
-- Name: idx_fin_res_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fin_res_status ON public.fin_reservations USING btree (status);


--
-- Name: idx_fin_snap_period; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fin_snap_period ON public.fin_revenue_snapshots USING btree (period_start, period_end);


--
-- Name: idx_finance_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_finance_date ON public.finance_invoices USING btree (date);


--
-- Name: idx_finance_source_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_finance_source_email ON public.finance_invoices USING btree (source_email_id);


--
-- Name: idx_finance_vendor; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_finance_vendor ON public.finance_invoices USING btree (vendor);


--
-- Name: idx_gl_business; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gl_business ON public.general_ledger USING btree (business);


--
-- Name: idx_gl_cabin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gl_cabin ON public.general_ledger USING btree (cabin);


--
-- Name: idx_gl_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gl_category ON public.general_ledger USING btree (category);


--
-- Name: idx_gl_checkin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gl_checkin ON public.guest_leads USING btree (check_in);


--
-- Name: idx_gl_doc_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gl_doc_type ON public.general_ledger USING btree (doc_type);


--
-- Name: idx_gl_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gl_email ON public.guest_leads USING btree (source_email_id);


--
-- Name: idx_gl_event; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gl_event ON public.guest_leads USING btree (event_type);


--
-- Name: idx_gl_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gl_status ON public.guest_leads USING btree (status);


--
-- Name: idx_gl_tax_year; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gl_tax_year ON public.general_ledger USING btree (tax_year);


--
-- Name: idx_guest_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_guest_email ON public.guest_profiles USING btree (email);


--
-- Name: idx_guest_last_contact; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_guest_last_contact ON public.guest_profiles USING btree (last_contact DESC);


--
-- Name: idx_guest_phone; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_guest_phone ON public.guest_profiles USING btree (phone_number);


--
-- Name: idx_guest_vip; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_guest_vip ON public.guest_profiles USING btree (vip_guest) WHERE (vip_guest = true);


--
-- Name: idx_je_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_je_date ON public.journal_entries USING btree (entry_date);


--
-- Name: idx_je_property; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_je_property ON public.journal_entries USING btree (property_id);


--
-- Name: idx_je_ref; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_je_ref ON public.journal_entries USING btree (reference_id);


--
-- Name: idx_je_ref_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_je_ref_type ON public.journal_entries USING btree (reference_type);


--
-- Name: idx_je_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_je_source ON public.journal_entries USING btree (source_system);


--
-- Name: idx_je_void; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_je_void ON public.journal_entries USING btree (is_void);


--
-- Name: idx_jli_account; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jli_account ON public.journal_line_items USING btree (account_id);


--
-- Name: idx_jli_entry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jli_entry ON public.journal_line_items USING btree (journal_entry_id);


--
-- Name: idx_lj_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lj_agent ON public.learning_judgments USING btree (agent_id);


--
-- Name: idx_lj_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lj_created ON public.learning_judgments USING btree (created_at);


--
-- Name: idx_lj_metric; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lj_metric ON public.learning_judgments USING btree (metric_name);


--
-- Name: idx_lj_passed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lj_passed ON public.learning_judgments USING btree (passed);


--
-- Name: idx_lo_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lo_agent ON public.learning_optimizations USING btree (agent_id);


--
-- Name: idx_lo_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lo_created ON public.learning_optimizations USING btree (created_at);


--
-- Name: idx_lo_method; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lo_method ON public.learning_optimizations USING btree (method);


--
-- Name: idx_market_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_market_action ON public.market_signals USING btree (action);


--
-- Name: idx_market_source_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_market_source_email ON public.market_signals USING btree (source_email_id);


--
-- Name: idx_market_ticker; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_market_ticker ON public.market_signals USING btree (ticker);


--
-- Name: idx_matters_client; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_matters_client ON public.legal_matters USING btree (client_id);


--
-- Name: idx_matters_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_matters_status ON public.legal_matters USING btree (status);


--
-- Name: idx_message_body_fts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_message_body_fts ON public.message_archive USING gin (to_tsvector('english'::regconfig, message_body));


--
-- Name: idx_message_direction; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_message_direction ON public.message_archive USING btree (direction);


--
-- Name: idx_message_external_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_message_external_id ON public.message_archive USING btree (external_id);


--
-- Name: idx_message_intent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_message_intent ON public.message_archive USING btree (intent);


--
-- Name: idx_message_phone; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_message_phone ON public.message_archive USING btree (phone_number);


--
-- Name: idx_message_property; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_message_property ON public.message_archive USING btree (property_id);


--
-- Name: idx_message_sent_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_message_sent_at ON public.message_archive USING btree (sent_at DESC);


--
-- Name: idx_message_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_message_source ON public.message_archive USING btree (source);


--
-- Name: idx_message_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_message_status ON public.message_archive USING btree (status);


--
-- Name: idx_message_training; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_message_training ON public.message_archive USING btree (used_for_training) WHERE (used_for_training = true);


--
-- Name: idx_ml_cabin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ml_cabin ON public.maintenance_log USING btree (cabin_name);


--
-- Name: idx_ml_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ml_date ON public.maintenance_log USING btree (generated_at);


--
-- Name: idx_ml_room; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ml_room ON public.maintenance_log USING btree (room_type);


--
-- Name: idx_ml_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ml_run ON public.maintenance_log USING btree (run_id);


--
-- Name: idx_ml_verdict; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ml_verdict ON public.maintenance_log USING btree (verdict);


--
-- Name: idx_mt_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mt_created ON public.model_telemetry USING btree (created_at);


--
-- Name: idx_mt_model; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mt_model ON public.model_telemetry USING btree (model_name);


--
-- Name: idx_mt_node; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mt_node ON public.model_telemetry USING btree (node);


--
-- Name: idx_mt_op; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mt_op ON public.model_telemetry USING btree (operation);


--
-- Name: idx_mt_success; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mt_success ON public.model_telemetry USING btree (success);


--
-- Name: idx_nas_vault_case_number; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_nas_vault_case_number ON public.nas_legal_vault USING btree (((metadata ->> 'case_number'::text)));


--
-- Name: idx_nas_vault_deadline; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_nas_vault_deadline ON public.nas_legal_vault USING btree (((metadata ->> 'next_deadline'::text)));


--
-- Name: idx_nas_vault_doc_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_nas_vault_doc_type ON public.nas_legal_vault USING btree (((metadata ->> 'doc_type'::text)));


--
-- Name: idx_nas_vault_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_nas_vault_embedding ON public.nas_legal_vault USING hnsw (embedding public.vector_cosine_ops);


--
-- Name: idx_nas_vault_priority; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_nas_vault_priority ON public.nas_legal_vault USING btree (((metadata ->> 'priority'::text)));


--
-- Name: idx_nas_vault_source_file; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_nas_vault_source_file ON public.nas_legal_vault USING btree (source_file);


--
-- Name: idx_nim_arm64_probe_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_nim_arm64_probe_date ON public.nim_arm64_probe_results USING btree (probe_date);


--
-- Name: idx_nim_arm64_probe_image; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_nim_arm64_probe_image ON public.nim_arm64_probe_results USING btree (image_path);


--
-- Name: idx_notes_matter; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notes_matter ON public.legal_matter_notes USING btree (matter_id);


--
-- Name: idx_ops_crew_role; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ops_crew_role ON public.ops_crew USING btree (role);


--
-- Name: idx_ops_crew_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ops_crew_status ON public.ops_crew USING btree (status);


--
-- Name: idx_ops_hist_guests_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ops_hist_guests_email ON public.ops_historical_guests USING btree (email);


--
-- Name: idx_ops_hist_guests_last_seen; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ops_hist_guests_last_seen ON public.ops_historical_guests USING btree (last_seen);


--
-- Name: idx_ops_hist_guests_phone; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ops_hist_guests_phone ON public.ops_historical_guests USING btree (phone);


--
-- Name: idx_ops_log_actor; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ops_log_actor ON public.ops_log USING btree (actor);


--
-- Name: idx_ops_log_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ops_log_entity ON public.ops_log USING btree (entity_type, entity_id);


--
-- Name: idx_ops_log_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ops_log_time ON public.ops_log USING btree ("timestamp");


--
-- Name: idx_ops_prop_streamline; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ops_prop_streamline ON public.ops_properties USING btree (streamline_id);


--
-- Name: idx_ops_props_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ops_props_name ON public.ops_properties USING btree (internal_name);


--
-- Name: idx_ops_tasks_assignee; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ops_tasks_assignee ON public.ops_tasks USING btree (assigned_to);


--
-- Name: idx_ops_tasks_deadline; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ops_tasks_deadline ON public.ops_tasks USING btree (deadline);


--
-- Name: idx_ops_tasks_priority; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ops_tasks_priority ON public.ops_tasks USING btree (priority);


--
-- Name: idx_ops_tasks_property; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ops_tasks_property ON public.ops_tasks USING btree (property_id);


--
-- Name: idx_ops_tasks_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ops_tasks_status ON public.ops_tasks USING btree (status);


--
-- Name: idx_ops_tasks_turnover; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ops_tasks_turnover ON public.ops_tasks USING btree (turnover_id);


--
-- Name: idx_ops_tasks_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ops_tasks_type ON public.ops_tasks USING btree (type);


--
-- Name: idx_ops_turn_checkout; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ops_turn_checkout ON public.ops_turnovers USING btree (checkout_time);


--
-- Name: idx_ops_turn_property; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ops_turn_property ON public.ops_turnovers USING btree (property_id);


--
-- Name: idx_ops_turn_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ops_turn_status ON public.ops_turnovers USING btree (status);


--
-- Name: idx_overrides_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_overrides_active ON public.ops_overrides USING btree (active, entity_type);


--
-- Name: idx_overrides_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_overrides_entity ON public.ops_overrides USING btree (entity_type, entity_id);


--
-- Name: idx_pe_event_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pe_event_type ON public.property_events USING btree (event_type);


--
-- Name: idx_pe_property_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pe_property_id ON public.property_events USING btree (property_id);


--
-- Name: idx_property_ai_enabled; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_property_ai_enabled ON public.property_sms_config USING btree (ai_enabled);


--
-- Name: idx_property_phone; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_property_phone ON public.property_sms_config USING btree (assigned_phone_number);


--
-- Name: idx_provider_enabled; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_provider_enabled ON public.sms_providers USING btree (enabled, priority) WHERE (enabled = true);


--
-- Name: idx_quarantine_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_quarantine_at ON public.quarantine_inbox USING btree (quarantined_at);


--
-- Name: idx_quarantine_sender; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_quarantine_sender ON public.quarantine_inbox USING btree (sender);


--
-- Name: idx_quarantine_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_quarantine_status ON public.email_quarantine USING btree (status) WHERE ((status)::text = 'quarantined'::text);


--
-- Name: idx_queue_attribution; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_queue_attribution ON public.agent_response_queue USING btree (phone_number, intent) WHERE ((intent)::text = 'proactive_sales'::text);


--
-- Name: idx_rag_section; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rag_section ON public.ruebarue_area_guide USING btree (section);


--
-- Name: idx_review_log_actor; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_review_log_actor ON public.email_intake_review_log USING btree (actor, created_at DESC);


--
-- Name: idx_review_log_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_review_log_email ON public.email_intake_review_log USING btree (email_id);


--
-- Name: idx_review_log_esc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_review_log_esc ON public.email_intake_review_log USING btree (escalation_id);


--
-- Name: idx_rkb_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rkb_category ON public.ruebarue_knowledge_base USING btree (category);


--
-- Name: idx_rkb_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rkb_source ON public.ruebarue_knowledge_base USING btree (source);


--
-- Name: idx_rl_cabin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rl_cabin ON public.revenue_ledger USING btree (cabin_name);


--
-- Name: idx_rl_cabin_date_run; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_rl_cabin_date_run ON public.revenue_ledger USING btree (cabin_name, target_date, run_id);


--
-- Name: idx_rl_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rl_date ON public.revenue_ledger USING btree (target_date);


--
-- Name: idx_rl_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rl_run ON public.revenue_ledger USING btree (run_id);


--
-- Name: idx_rl_signal; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rl_signal ON public.revenue_ledger USING btree (trading_signal);


--
-- Name: idx_routing_rules_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_routing_rules_active ON public.email_routing_rules USING btree (rule_type, is_active) WHERE (is_active = true);


--
-- Name: idx_rqf_brain; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rqf_brain ON public.rag_query_feedback USING btree (brain);


--
-- Name: idx_rqf_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rqf_created ON public.rag_query_feedback USING btree (created_at);


--
-- Name: idx_rqf_quality; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rqf_quality ON public.rag_query_feedback USING btree (response_quality);


--
-- Name: idx_sanitizer_log_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sanitizer_log_run ON public.data_sanitizer_log USING btree (run_id);


--
-- Name: idx_sanitizer_log_table; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sanitizer_log_table ON public.data_sanitizer_log USING btree (table_name, column_name);


--
-- Name: idx_sensors_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sensors_active ON public.email_sensors USING btree (is_active) WHERE (is_active = true);


--
-- Name: idx_sentinel_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sentinel_source ON public.sentinel_state USING btree (source);


--
-- Name: idx_si_cabin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_si_cabin ON public.sales_intel USING btree (cabin_name);


--
-- Name: idx_si_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_si_email ON public.sales_intel USING btree (source_email_id);


--
-- Name: idx_si_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_si_type ON public.sales_intel USING btree (signal_type);


--
-- Name: idx_sr_domain; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sr_domain ON public.sender_registry USING btree (domain);


--
-- Name: idx_sr_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sr_email ON public.sender_registry USING btree (email_address);


--
-- Name: idx_sr_signal; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sr_signal ON public.sender_registry USING btree (signal_ratio);


--
-- Name: idx_sr_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sr_status ON public.sender_registry USING btree (status);


--
-- Name: idx_starred_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_starred_embedding ON public.starred_responses USING ivfflat (embedding public.vector_cosine_ops) WITH (lists='10');


--
-- Name: idx_starred_intent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_starred_intent ON public.starred_responses USING btree (intent);


--
-- Name: idx_system_directives_active_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_system_directives_active_created ON public.system_directives USING btree (active, created_at);


--
-- Name: idx_tb_property; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tb_property ON public.trust_balance USING btree (property_id);


--
-- Name: idx_thread_last_message; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_thread_last_message ON public.conversation_threads USING btree (last_message_at DESC);


--
-- Name: idx_thread_phone; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_thread_phone ON public.conversation_threads USING btree (phone_number);


--
-- Name: idx_thread_property; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_thread_property ON public.conversation_threads USING btree (property_id);


--
-- Name: idx_thread_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_thread_status ON public.conversation_threads USING btree (status);


--
-- Name: idx_trace_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trace_created ON public.recursive_trace_log USING btree (created_at);


--
-- Name: idx_trace_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trace_run_id ON public.recursive_trace_log USING btree (run_id);


--
-- Name: idx_trace_stage; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trace_stage ON public.recursive_trace_log USING btree (stage);


--
-- Name: idx_trace_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trace_user ON public.recursive_trace_log USING btree (user_id);


--
-- Name: idx_training_intent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_training_intent ON public.ai_training_labels USING btree (labeled_intent);


--
-- Name: idx_training_labeled_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_training_labeled_at ON public.ai_training_labels USING btree (labeled_at DESC);


--
-- Name: idx_training_message; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_training_message ON public.ai_training_labels USING btree (message_id);


--
-- Name: idx_vault_delta_citation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vault_delta_citation ON public.vault_delta USING btree (citation);


--
-- Name: idx_vault_delta_court; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vault_delta_court ON public.vault_delta USING btree (court);


--
-- Name: idx_vault_delta_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vault_delta_embedding ON public.vault_delta USING ivfflat (embedding public.vector_cosine_ops) WITH (lists='100');


--
-- Name: idx_vault_delta_text_search; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vault_delta_text_search ON public.vault_delta USING gin (text_search);


--
-- Name: idx_vis_ext; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vis_ext ON public.ops_visuals USING btree (file_ext);


--
-- Name: idx_vis_path; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vis_path ON public.ops_visuals USING btree (file_path);


--
-- Name: idx_vis_prop; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vis_prop ON public.ops_visuals USING btree (property_id);


--
-- Name: idx_vis_propname; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vis_propname ON public.ops_visuals USING btree (property_name);


--
-- Name: idx_vis_room; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vis_room ON public.ops_visuals USING btree (room_type);


--
-- Name: idx_vis_scanned; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vis_scanned ON public.ops_visuals USING btree (scanned_at);


--
-- Name: idx_vis_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vis_status ON public.ops_visuals USING btree (status);


--
-- Name: idx_visual_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_visual_hash ON public.ops_visuals USING btree (visual_hash);


--
-- Name: ix_agent_memory_model; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_memory_model ON public.agent_memory USING btree (model);


--
-- Name: ix_agent_memory_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_memory_request_id ON public.agent_memory USING btree (request_id);


--
-- Name: ix_agent_telemetry_error_class; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_telemetry_error_class ON public.agent_telemetry USING btree (error_class);


--
-- Name: ix_agent_telemetry_model; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_telemetry_model ON public.agent_telemetry USING btree (model);


--
-- Name: ix_agent_telemetry_prompt_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_telemetry_prompt_hash ON public.agent_telemetry USING btree (prompt_hash);


--
-- Name: ix_agent_telemetry_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_telemetry_request_id ON public.agent_telemetry USING btree (request_id);


--
-- Name: ix_agent_telemetry_user_feedback_signal; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_telemetry_user_feedback_signal ON public.agent_telemetry USING btree (user_feedback_signal);


--
-- Name: ix_system_directives_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_system_directives_active ON public.system_directives USING btree (active);


--
-- Name: attorneys trg_attorneys_updated; Type: TRIGGER; Schema: legal_cmd; Owner: -
--

CREATE TRIGGER trg_attorneys_updated BEFORE UPDATE ON legal_cmd.attorneys FOR EACH ROW EXECUTE FUNCTION legal_cmd.update_timestamp();


--
-- Name: matters trg_matters_updated; Type: TRIGGER; Schema: legal_cmd; Owner: -
--

CREATE TRIGGER trg_matters_updated BEFORE UPDATE ON legal_cmd.matters FOR EACH ROW EXECUTE FUNCTION legal_cmd.update_timestamp();


--
-- Name: meetings trg_meetings_updated; Type: TRIGGER; Schema: legal_cmd; Owner: -
--

CREATE TRIGGER trg_meetings_updated BEFORE UPDATE ON legal_cmd.meetings FOR EACH ROW EXECUTE FUNCTION legal_cmd.update_timestamp();


--
-- Name: journal_line_items trg_immutable_line_items; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_immutable_line_items BEFORE DELETE OR UPDATE ON public.journal_line_items FOR EACH ROW EXECUTE FUNCTION public.enforce_immutable_line_items();


--
-- Name: journal_entries trg_journal_entry_integrity; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_journal_entry_integrity BEFORE DELETE OR UPDATE ON public.journal_entries FOR EACH ROW EXECUTE FUNCTION public.enforce_journal_entry_integrity();


--
-- Name: journal_line_items trg_verify_balance; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER trg_verify_balance AFTER INSERT OR UPDATE ON public.journal_line_items DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.verify_journal_balance();


--
-- Name: conversation_threads update_conversation_threads_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_conversation_threads_updated_at BEFORE UPDATE ON public.conversation_threads FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: guest_profiles update_guest_profiles_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_guest_profiles_updated_at BEFORE UPDATE ON public.guest_profiles FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: message_archive update_message_archive_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_message_archive_updated_at BEFORE UPDATE ON public.message_archive FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: account_mappings account_mappings_credit_account_fkey; Type: FK CONSTRAINT; Schema: division_a; Owner: -
--

ALTER TABLE ONLY division_a.account_mappings
    ADD CONSTRAINT account_mappings_credit_account_fkey FOREIGN KEY (credit_account) REFERENCES division_a.chart_of_accounts(code);


--
-- Name: account_mappings account_mappings_debit_account_fkey; Type: FK CONSTRAINT; Schema: division_a; Owner: -
--

ALTER TABLE ONLY division_a.account_mappings
    ADD CONSTRAINT account_mappings_debit_account_fkey FOREIGN KEY (debit_account) REFERENCES division_a.chart_of_accounts(code);


--
-- Name: general_ledger general_ledger_account_code_fkey; Type: FK CONSTRAINT; Schema: division_a; Owner: -
--

ALTER TABLE ONLY division_a.general_ledger
    ADD CONSTRAINT general_ledger_account_code_fkey FOREIGN KEY (account_code) REFERENCES division_a.chart_of_accounts(code);


--
-- Name: general_ledger general_ledger_journal_entry_id_fkey; Type: FK CONSTRAINT; Schema: division_a; Owner: -
--

ALTER TABLE ONLY division_a.general_ledger
    ADD CONSTRAINT general_ledger_journal_entry_id_fkey FOREIGN KEY (journal_entry_id) REFERENCES division_a.journal_entries(entry_id);


--
-- Name: account_mappings account_mappings_credit_account_fkey; Type: FK CONSTRAINT; Schema: division_b; Owner: -
--

ALTER TABLE ONLY division_b.account_mappings
    ADD CONSTRAINT account_mappings_credit_account_fkey FOREIGN KEY (credit_account) REFERENCES division_b.chart_of_accounts(code);


--
-- Name: account_mappings account_mappings_debit_account_fkey; Type: FK CONSTRAINT; Schema: division_b; Owner: -
--

ALTER TABLE ONLY division_b.account_mappings
    ADD CONSTRAINT account_mappings_debit_account_fkey FOREIGN KEY (debit_account) REFERENCES division_b.chart_of_accounts(code);


--
-- Name: general_ledger general_ledger_account_code_fkey; Type: FK CONSTRAINT; Schema: division_b; Owner: -
--

ALTER TABLE ONLY division_b.general_ledger
    ADD CONSTRAINT general_ledger_account_code_fkey FOREIGN KEY (account_code) REFERENCES division_b.chart_of_accounts(code);


--
-- Name: general_ledger general_ledger_journal_entry_id_fkey; Type: FK CONSTRAINT; Schema: division_b; Owner: -
--

ALTER TABLE ONLY division_b.general_ledger
    ADD CONSTRAINT general_ledger_journal_entry_id_fkey FOREIGN KEY (journal_entry_id) REFERENCES division_b.journal_entries(entry_id);


--
-- Name: change_orders change_orders_project_id_fkey; Type: FK CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.change_orders
    ADD CONSTRAINT change_orders_project_id_fkey FOREIGN KEY (project_id) REFERENCES engineering.projects(id);


--
-- Name: compliance_log compliance_log_drawing_id_fkey; Type: FK CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.compliance_log
    ADD CONSTRAINT compliance_log_drawing_id_fkey FOREIGN KEY (drawing_id) REFERENCES engineering.drawings(id);


--
-- Name: compliance_log compliance_log_project_id_fkey; Type: FK CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.compliance_log
    ADD CONSTRAINT compliance_log_project_id_fkey FOREIGN KEY (project_id) REFERENCES engineering.projects(id);


--
-- Name: compliance_log compliance_log_property_id_fkey; Type: FK CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.compliance_log
    ADD CONSTRAINT compliance_log_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id);


--
-- Name: cost_estimates cost_estimates_project_id_fkey; Type: FK CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.cost_estimates
    ADD CONSTRAINT cost_estimates_project_id_fkey FOREIGN KEY (project_id) REFERENCES engineering.projects(id);


--
-- Name: drawings drawings_project_id_fkey; Type: FK CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.drawings
    ADD CONSTRAINT drawings_project_id_fkey FOREIGN KEY (project_id) REFERENCES engineering.projects(id);


--
-- Name: drawings drawings_property_id_fkey; Type: FK CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.drawings
    ADD CONSTRAINT drawings_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id);


--
-- Name: inspections inspections_permit_id_fkey; Type: FK CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.inspections
    ADD CONSTRAINT inspections_permit_id_fkey FOREIGN KEY (permit_id) REFERENCES engineering.permits(id);


--
-- Name: inspections inspections_project_id_fkey; Type: FK CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.inspections
    ADD CONSTRAINT inspections_project_id_fkey FOREIGN KEY (project_id) REFERENCES engineering.projects(id);


--
-- Name: inspections inspections_property_id_fkey; Type: FK CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.inspections
    ADD CONSTRAINT inspections_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id);


--
-- Name: mep_systems mep_systems_property_id_fkey; Type: FK CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.mep_systems
    ADD CONSTRAINT mep_systems_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id);


--
-- Name: permits permits_project_id_fkey; Type: FK CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.permits
    ADD CONSTRAINT permits_project_id_fkey FOREIGN KEY (project_id) REFERENCES engineering.projects(id);


--
-- Name: permits permits_property_id_fkey; Type: FK CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.permits
    ADD CONSTRAINT permits_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id);


--
-- Name: projects projects_property_id_fkey; Type: FK CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.projects
    ADD CONSTRAINT projects_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id);


--
-- Name: punch_items punch_items_inspection_id_fkey; Type: FK CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.punch_items
    ADD CONSTRAINT punch_items_inspection_id_fkey FOREIGN KEY (inspection_id) REFERENCES engineering.inspections(id);


--
-- Name: punch_items punch_items_project_id_fkey; Type: FK CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.punch_items
    ADD CONSTRAINT punch_items_project_id_fkey FOREIGN KEY (project_id) REFERENCES engineering.projects(id);


--
-- Name: rfis rfis_project_id_fkey; Type: FK CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.rfis
    ADD CONSTRAINT rfis_project_id_fkey FOREIGN KEY (project_id) REFERENCES engineering.projects(id);


--
-- Name: submittals submittals_project_id_fkey; Type: FK CONSTRAINT; Schema: engineering; Owner: -
--

ALTER TABLE ONLY engineering.submittals
    ADD CONSTRAINT submittals_project_id_fkey FOREIGN KEY (project_id) REFERENCES engineering.projects(id);


--
-- Name: classification_rules classification_rules_source_vendor_id_fkey; Type: FK CONSTRAINT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.classification_rules
    ADD CONSTRAINT classification_rules_source_vendor_id_fkey FOREIGN KEY (source_vendor_id) REFERENCES finance.vendor_classifications(id);


--
-- Name: extraction_log extraction_log_email_id_fkey; Type: FK CONSTRAINT; Schema: hedge_fund; Owner: -
--

ALTER TABLE ONLY hedge_fund.extraction_log
    ADD CONSTRAINT extraction_log_email_id_fkey FOREIGN KEY (email_id) REFERENCES public.email_archive(id) ON DELETE SET NULL;


--
-- Name: market_signals market_signals_source_email_id_fkey; Type: FK CONSTRAINT; Schema: hedge_fund; Owner: -
--

ALTER TABLE ONLY hedge_fund.market_signals
    ADD CONSTRAINT market_signals_source_email_id_fkey FOREIGN KEY (source_email_id) REFERENCES public.email_archive(id) ON DELETE SET NULL;


--
-- Name: relationships relationships_from_entity_id_fkey; Type: FK CONSTRAINT; Schema: intelligence; Owner: -
--

ALTER TABLE ONLY intelligence.relationships
    ADD CONSTRAINT relationships_from_entity_id_fkey FOREIGN KEY (from_entity_id) REFERENCES intelligence.entities(id) ON DELETE CASCADE;


--
-- Name: relationships relationships_to_entity_id_fkey; Type: FK CONSTRAINT; Schema: intelligence; Owner: -
--

ALTER TABLE ONLY intelligence.relationships
    ADD CONSTRAINT relationships_to_entity_id_fkey FOREIGN KEY (to_entity_id) REFERENCES intelligence.entities(id) ON DELETE CASCADE;


--
-- Name: case_actions case_actions_case_id_fkey; Type: FK CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.case_actions
    ADD CONSTRAINT case_actions_case_id_fkey FOREIGN KEY (case_id) REFERENCES legal.cases(id);


--
-- Name: case_evidence case_evidence_case_id_fkey; Type: FK CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.case_evidence
    ADD CONSTRAINT case_evidence_case_id_fkey FOREIGN KEY (case_id) REFERENCES legal.cases(id);


--
-- Name: case_watchdog case_watchdog_case_id_fkey; Type: FK CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.case_watchdog
    ADD CONSTRAINT case_watchdog_case_id_fkey FOREIGN KEY (case_id) REFERENCES legal.cases(id);


--
-- Name: correspondence correspondence_case_id_fkey; Type: FK CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.correspondence
    ADD CONSTRAINT correspondence_case_id_fkey FOREIGN KEY (case_id) REFERENCES legal.cases(id);


--
-- Name: deadlines deadlines_case_id_fkey; Type: FK CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.deadlines
    ADD CONSTRAINT deadlines_case_id_fkey FOREIGN KEY (case_id) REFERENCES legal.cases(id);


--
-- Name: filings filings_case_id_fkey; Type: FK CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.filings
    ADD CONSTRAINT filings_case_id_fkey FOREIGN KEY (case_id) REFERENCES legal.cases(id);


--
-- Name: ingest_runs fk_ingest_runs_case_slug; Type: FK CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.ingest_runs
    ADD CONSTRAINT fk_ingest_runs_case_slug FOREIGN KEY (case_slug) REFERENCES legal.cases(case_slug) ON DELETE CASCADE;


--
-- Name: case_precedents fk_precedent_case_slug; Type: FK CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.case_precedents
    ADD CONSTRAINT fk_precedent_case_slug FOREIGN KEY (case_slug) REFERENCES legal.cases(case_slug);


--
-- Name: vault_documents fk_vault_documents_case_slug; Type: FK CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.vault_documents
    ADD CONSTRAINT fk_vault_documents_case_slug FOREIGN KEY (case_slug) REFERENCES legal.cases(case_slug) ON DELETE CASCADE;


--
-- Name: uploads uploads_case_id_fkey; Type: FK CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.uploads
    ADD CONSTRAINT uploads_case_id_fkey FOREIGN KEY (case_id) REFERENCES legal.cases(id);


--
-- Name: uploads uploads_filing_id_fkey; Type: FK CONSTRAINT; Schema: legal; Owner: -
--

ALTER TABLE ONLY legal.uploads
    ADD CONSTRAINT uploads_filing_id_fkey FOREIGN KEY (filing_id) REFERENCES legal.filings(id);


--
-- Name: attorney_scoring attorney_scoring_attorney_id_fkey; Type: FK CONSTRAINT; Schema: legal_cmd; Owner: -
--

ALTER TABLE ONLY legal_cmd.attorney_scoring
    ADD CONSTRAINT attorney_scoring_attorney_id_fkey FOREIGN KEY (attorney_id) REFERENCES legal_cmd.attorneys(id) ON DELETE CASCADE;


--
-- Name: documents documents_matter_id_fkey; Type: FK CONSTRAINT; Schema: legal_cmd; Owner: -
--

ALTER TABLE ONLY legal_cmd.documents
    ADD CONSTRAINT documents_matter_id_fkey FOREIGN KEY (matter_id) REFERENCES legal_cmd.matters(id);


--
-- Name: matters matters_attorney_id_fkey; Type: FK CONSTRAINT; Schema: legal_cmd; Owner: -
--

ALTER TABLE ONLY legal_cmd.matters
    ADD CONSTRAINT matters_attorney_id_fkey FOREIGN KEY (attorney_id) REFERENCES legal_cmd.attorneys(id);


--
-- Name: meetings meetings_attorney_id_fkey; Type: FK CONSTRAINT; Schema: legal_cmd; Owner: -
--

ALTER TABLE ONLY legal_cmd.meetings
    ADD CONSTRAINT meetings_attorney_id_fkey FOREIGN KEY (attorney_id) REFERENCES legal_cmd.attorneys(id);


--
-- Name: meetings meetings_matter_id_fkey; Type: FK CONSTRAINT; Schema: legal_cmd; Owner: -
--

ALTER TABLE ONLY legal_cmd.meetings
    ADD CONSTRAINT meetings_matter_id_fkey FOREIGN KEY (matter_id) REFERENCES legal_cmd.matters(id);


--
-- Name: timeline timeline_matter_id_fkey; Type: FK CONSTRAINT; Schema: legal_cmd; Owner: -
--

ALTER TABLE ONLY legal_cmd.timeline
    ADD CONSTRAINT timeline_matter_id_fkey FOREIGN KEY (matter_id) REFERENCES legal_cmd.matters(id);


--
-- Name: timeline timeline_related_attorney_id_fkey; Type: FK CONSTRAINT; Schema: legal_cmd; Owner: -
--

ALTER TABLE ONLY legal_cmd.timeline
    ADD CONSTRAINT timeline_related_attorney_id_fkey FOREIGN KEY (related_attorney_id) REFERENCES legal_cmd.attorneys(id);


--
-- Name: timeline timeline_related_meeting_id_fkey; Type: FK CONSTRAINT; Schema: legal_cmd; Owner: -
--

ALTER TABLE ONLY legal_cmd.timeline
    ADD CONSTRAINT timeline_related_meeting_id_fkey FOREIGN KEY (related_meeting_id) REFERENCES legal_cmd.meetings(id);


--
-- Name: ab_test_observations ab_test_observations_test_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ab_test_observations
    ADD CONSTRAINT ab_test_observations_test_id_fkey FOREIGN KEY (test_id) REFERENCES public.ab_tests(id);


--
-- Name: accounts accounts_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT accounts_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.accounts(id);


--
-- Name: active_learning_queue active_learning_queue_judgment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.active_learning_queue
    ADD CONSTRAINT active_learning_queue_judgment_id_fkey FOREIGN KEY (judgment_id) REFERENCES public.learning_judgments(id);


--
-- Name: agent_learning_log agent_learning_log_queue_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_learning_log
    ADD CONSTRAINT agent_learning_log_queue_id_fkey FOREIGN KEY (queue_id) REFERENCES public.agent_response_queue(id);


--
-- Name: agent_response_queue agent_response_queue_inbound_message_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_response_queue
    ADD CONSTRAINT agent_response_queue_inbound_message_id_fkey FOREIGN KEY (inbound_message_id) REFERENCES public.message_archive(id);


--
-- Name: ai_training_labels ai_training_labels_message_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_training_labels
    ADD CONSTRAINT ai_training_labels_message_id_fkey FOREIGN KEY (message_id) REFERENCES public.message_archive(id);


--
-- Name: anomaly_flags anomaly_flags_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.anomaly_flags
    ADD CONSTRAINT anomaly_flags_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.accounts(id);


--
-- Name: anomaly_flags anomaly_flags_journal_entry_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.anomaly_flags
    ADD CONSTRAINT anomaly_flags_journal_entry_id_fkey FOREIGN KEY (journal_entry_id) REFERENCES public.journal_entries(id);


--
-- Name: asset_docs asset_docs_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_docs
    ADD CONSTRAINT asset_docs_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id);


--
-- Name: email_escalation_queue email_escalation_queue_email_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_escalation_queue
    ADD CONSTRAINT email_escalation_queue_email_id_fkey FOREIGN KEY (email_id) REFERENCES public.email_archive(id);


--
-- Name: email_intake_review_log email_intake_review_log_email_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_intake_review_log
    ADD CONSTRAINT email_intake_review_log_email_id_fkey FOREIGN KEY (email_id) REFERENCES public.email_archive(id);


--
-- Name: email_intake_review_log email_intake_review_log_escalation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_intake_review_log
    ADD CONSTRAINT email_intake_review_log_escalation_id_fkey FOREIGN KEY (escalation_id) REFERENCES public.email_escalation_queue(id);


--
-- Name: email_quarantine email_quarantine_rule_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_quarantine
    ADD CONSTRAINT email_quarantine_rule_id_fkey FOREIGN KEY (rule_id) REFERENCES public.email_routing_rules(id);


--
-- Name: finance_invoices finance_invoices_source_email_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_invoices
    ADD CONSTRAINT finance_invoices_source_email_id_fkey FOREIGN KEY (source_email_id) REFERENCES public.email_archive(id) ON DELETE CASCADE;


--
-- Name: fortress_api_keys fortress_api_keys_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fortress_api_keys
    ADD CONSTRAINT fortress_api_keys_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES public.fortress_users(id);


--
-- Name: guest_leads guest_leads_source_email_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.guest_leads
    ADD CONSTRAINT guest_leads_source_email_id_fkey FOREIGN KEY (source_email_id) REFERENCES public.email_archive(id);


--
-- Name: journal_line_items journal_line_items_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_line_items
    ADD CONSTRAINT journal_line_items_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.accounts(id);


--
-- Name: journal_line_items journal_line_items_journal_entry_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_line_items
    ADD CONSTRAINT journal_line_items_journal_entry_id_fkey FOREIGN KEY (journal_entry_id) REFERENCES public.journal_entries(id) ON DELETE CASCADE;


--
-- Name: legal_docket legal_docket_matter_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legal_docket
    ADD CONSTRAINT legal_docket_matter_id_fkey FOREIGN KEY (matter_id) REFERENCES public.legal_matters(matter_id);


--
-- Name: legal_matter_notes legal_matter_notes_matter_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legal_matter_notes
    ADD CONSTRAINT legal_matter_notes_matter_id_fkey FOREIGN KEY (matter_id) REFERENCES public.legal_matters(matter_id);


--
-- Name: legal_matters legal_matters_client_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legal_matters
    ADD CONSTRAINT legal_matters_client_id_fkey FOREIGN KEY (client_id) REFERENCES public.legal_clients(client_id);


--
-- Name: ops_tasks ops_tasks_assigned_to_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ops_tasks
    ADD CONSTRAINT ops_tasks_assigned_to_fkey FOREIGN KEY (assigned_to) REFERENCES public.ops_crew(id);


--
-- Name: ops_tasks ops_tasks_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ops_tasks
    ADD CONSTRAINT ops_tasks_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.ops_properties(property_id);


--
-- Name: ops_tasks ops_tasks_turnover_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ops_tasks
    ADD CONSTRAINT ops_tasks_turnover_id_fkey FOREIGN KEY (turnover_id) REFERENCES public.ops_turnovers(id);


--
-- Name: ops_turnovers ops_turnovers_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ops_turnovers
    ADD CONSTRAINT ops_turnovers_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.ops_properties(property_id);


--
-- Name: ops_visuals ops_visuals_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ops_visuals
    ADD CONSTRAINT ops_visuals_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.ops_properties(property_id) ON DELETE SET NULL;


--
-- Name: property_events property_events_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.property_events
    ADD CONSTRAINT property_events_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id);


--
-- Name: property_sms_config property_sms_config_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.property_sms_config
    ADD CONSTRAINT property_sms_config_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.sms_providers(id);


--
-- Name: sales_intel sales_intel_source_email_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sales_intel
    ADD CONSTRAINT sales_intel_source_email_id_fkey FOREIGN KEY (source_email_id) REFERENCES public.email_archive(id);


--
-- Name: trust_balance trust_balance_last_entry_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trust_balance
    ADD CONSTRAINT trust_balance_last_entry_id_fkey FOREIGN KEY (last_entry_id) REFERENCES public.journal_entries(id);


--
-- PostgreSQL database dump complete
--

\unrestrict VUrcdL6h86Va4b8PalMVliVEj9OibDpqKcdRaRctoyg85SNJEnJ3GJKYJj1pYCh
