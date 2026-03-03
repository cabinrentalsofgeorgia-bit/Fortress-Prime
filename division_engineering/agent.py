"""
Division Engineering Agent — "The Architect"
==============================================
The primary operational agent for CROG Engineering Division.

Persona:
    Methodical, code-compliant, precision-obsessed.
    Thinks in blueprints, schedules, and load calculations.
    Zero tolerance for code violations. Obsessive about permitting.

Responsibilities:
    1. Ingest and classify engineering documents (plans, specs, surveys)
    2. Track construction projects from concept through Certificate of Occupancy
    3. Monitor permit status and inspection schedules
    4. Analyze drawings (architectural, civil, mechanical) via Vision OCR
    5. Enforce Georgia Building Code / Fannin County regulations
    6. Manage MEP system inventories across all properties
    7. Report metrics UP to the Sovereign (never laterally)
    8. Self-improve via the OODA recursive loop when variance > 5%

Three Disciplines:
    - Architectural: Building design, layouts, renovations, ADA compliance
    - Civil:         Site plans, grading, drainage, septic, stormwater, surveys
    - Mechanical:    HVAC, plumbing, electrical, fire protection, hot tubs

Module: CF-10 — The Drawing Board
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from config import captain_think, CAPTAIN_URL

logger = logging.getLogger("division_engineering.agent")

# Division identifier (used by firewall and sovereign)
DIVISION_ID = "division_engineering"
DIVISION_NAME = "CROG Engineering — Architectural & Engineering Intelligence"

# Fast model for routine classification; 70b reserved for Sovereign
CATEGORIZATION_MODEL = "deepseek-r1:8b"


def _fast_categorize(prompt: str, system_role: str, temperature: float = 0.15) -> str:
    """
    Fast LLM call using deepseek-r1:8b for routine document/project classification.

    Engineering uses temperature 0.15 — slightly warmer than Division B's 0.1
    to allow creative interpretation of ambiguous drawings, but cooler than
    Division A's 0.2 because code compliance demands precision.
    """
    full_prompt = f"System: {system_role}\n\nUser: {prompt}"
    payload = {
        "model": CATEGORIZATION_MODEL,
        "prompt": full_prompt,
        "format": "json",
        "stream": False,
        "options": {"temperature": temperature, "num_predict": 1024},
    }
    try:
        resp = requests.post(
            f"{CAPTAIN_URL}/api/generate", json=payload, timeout=300,
        )
        resp.raise_for_status()
        return resp.json().get("response", "")
    except Exception as e:
        return f"[CATEGORIZE ERROR] {e}"


# =============================================================================
# ENGINEERING DISCIPLINES
# =============================================================================

class Discipline:
    """Engineering discipline identifiers."""
    ARCHITECTURAL = "architectural"
    CIVIL = "civil"
    MECHANICAL = "mechanical"
    STRUCTURAL = "structural"
    ELECTRICAL = "electrical"
    PLUMBING = "plumbing"
    FIRE_PROTECTION = "fire_protection"
    GENERAL = "general"


# Project lifecycle phases
class ProjectPhase:
    """Construction project lifecycle phases."""
    CONCEPT = "concept"                  # Idea / feasibility
    SCHEMATIC_DESIGN = "schematic"       # SD — massing, layout
    DESIGN_DEVELOPMENT = "dd"            # DD — refine systems
    CONSTRUCTION_DOCS = "cd"             # CD — permit-ready drawings
    PERMITTING = "permitting"            # Permit application submitted
    BIDDING = "bidding"                  # Contractor selection
    CONSTRUCTION = "construction"        # Active build
    PUNCH_LIST = "punch_list"            # Final corrections
    INSPECTION = "inspection"            # Final inspections
    CERTIFICATE_OF_OCCUPANCY = "co"      # CO issued — project complete
    CLOSEOUT = "closeout"                # Warranty period, as-builts filed
    ON_HOLD = "on_hold"
    CANCELLED = "cancelled"


# Document types specific to engineering
class DocType:
    """Engineering document classifications."""
    # Architectural
    FLOOR_PLAN = "Floor_Plan"
    ELEVATION = "Elevation"
    SECTION = "Section"
    DETAIL = "Detail"
    FINISH_SCHEDULE = "Finish_Schedule"
    DOOR_SCHEDULE = "Door_Schedule"
    WINDOW_SCHEDULE = "Window_Schedule"
    REFLECTED_CEILING = "Reflected_Ceiling_Plan"
    INTERIOR_ELEVATION = "Interior_Elevation"
    ADA_PLAN = "ADA_Compliance_Plan"
    RENOVATION_PLAN = "Renovation_Plan"
    AS_BUILT = "As_Built"
    SPEC_BOOK = "Specification_Book"

    # Civil
    SITE_PLAN = "Site_Plan"
    GRADING_PLAN = "Grading_Plan"
    DRAINAGE_PLAN = "Drainage_Plan"
    UTILITY_PLAN = "Utility_Plan"
    SEPTIC_PLAN = "Septic_Plan"
    EROSION_CONTROL = "Erosion_Control_Plan"
    STORMWATER = "Stormwater_Plan"
    TOPO_SURVEY = "Topographic_Survey"
    BOUNDARY_SURVEY = "Boundary_Survey"
    SOIL_REPORT = "Soil_Report"
    PERC_TEST = "Percolation_Test"
    WETLAND_DELINEATION = "Wetland_Delineation"

    # Structural
    FOUNDATION_PLAN = "Foundation_Plan"
    FRAMING_PLAN = "Framing_Plan"
    STRUCTURAL_CALC = "Structural_Calculations"
    LOAD_DIAGRAM = "Load_Diagram"

    # Mechanical / MEP
    HVAC_PLAN = "HVAC_Plan"
    HVAC_CALC = "HVAC_Load_Calculation"
    PLUMBING_PLAN = "Plumbing_Plan"
    ELECTRICAL_PLAN = "Electrical_Plan"
    PANEL_SCHEDULE = "Panel_Schedule"
    FIRE_PROTECTION_PLAN = "Fire_Protection_Plan"
    FIRE_SPRINKLER = "Fire_Sprinkler_Plan"
    HOT_TUB_SPEC = "Hot_Tub_Specification"
    GENERATOR_SPEC = "Generator_Specification"
    ENERGY_CALC = "Energy_Calculation"

    # Permits & Inspections
    BUILDING_PERMIT = "Building_Permit"
    MECHANICAL_PERMIT = "Mechanical_Permit"
    ELECTRICAL_PERMIT = "Electrical_Permit"
    PLUMBING_PERMIT = "Plumbing_Permit"
    SEPTIC_PERMIT = "Septic_Permit"
    GRADING_PERMIT = "Grading_Permit"
    INSPECTION_REPORT = "Inspection_Report"
    CERTIFICATE_OF_OCCUPANCY = "Certificate_of_Occupancy"
    VARIANCE_REQUEST = "Variance_Request"

    # General
    ENGINEERING_REPORT = "Engineering_Report"
    COST_ESTIMATE = "Cost_Estimate"
    CHANGE_ORDER = "Change_Order"
    RFI = "Request_for_Information"
    SUBMITTAL = "Submittal"
    SHOP_DRAWING = "Shop_Drawing"
    PUNCH_LIST = "Punch_List"
    WARRANTY = "Warranty"
    UNKNOWN = "Unknown"


# =============================================================================
# AGENT STATE
# =============================================================================

@dataclass
class EngineeringAgentState:
    """Operational state for the Engineering Division agent."""

    # Current cycle
    cycle_id: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Document processing
    pending_documents: List[Dict[str, Any]] = field(default_factory=list)
    classified_documents: List[Dict[str, Any]] = field(default_factory=list)
    ambiguous_documents: List[Dict[str, Any]] = field(default_factory=list)

    # Active projects
    active_projects: List[Dict[str, Any]] = field(default_factory=list)

    # Permit tracking
    pending_permits: List[Dict[str, Any]] = field(default_factory=list)
    pending_inspections: List[Dict[str, Any]] = field(default_factory=list)

    # MEP system inventory (per-property)
    mep_inventory: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Code compliance flags
    compliance_issues: List[Dict[str, Any]] = field(default_factory=list)

    # Metrics for Sovereign reporting
    metrics: Dict[str, float] = field(default_factory=dict)
    anomalies: List[Dict[str, Any]] = field(default_factory=list)

    # Learned classification rules
    classification_rules: Dict[str, Dict[str, str]] = field(default_factory=dict)


# =============================================================================
# SYSTEM PROMPT
# =============================================================================

SYSTEM_PROMPT = """You are The Architect — the engineering intelligence agent for CROG, LLC.

DIVISION: Engineering Division (Division 5 — The Drawing Board)
MODULE: CF-10
PERSONA: Methodical, code-compliant, precision-obsessed. You think in blueprints,
         schedules, and load calculations. Zero tolerance for code violations.

SCOPE: Full-suite Architectural & Engineering intelligence for Cabin Rentals of Georgia.
    - ARCHITECTURAL: Building plans, floor plans, elevations, sections, details,
      finish schedules, ADA compliance, renovation plans, interior design.
    - CIVIL: Site plans, grading, drainage, septic systems, erosion control,
      stormwater management, topographic surveys, boundary surveys, soil reports,
      percolation tests, wetland delineations.
    - STRUCTURAL: Foundation plans, framing plans, structural calculations, load diagrams.
    - MECHANICAL (MEP): HVAC plans & load calcs, plumbing plans, electrical plans,
      panel schedules, fire protection/sprinkler plans, hot tub specifications,
      generator specs, energy calculations.
    - PERMITS & INSPECTIONS: Building/mechanical/electrical/plumbing/septic/grading
      permits, inspection reports, certificates of occupancy, variance requests.
    - PROJECT MANAGEMENT: Cost estimates, change orders, RFIs, submittals,
      shop drawings, punch lists, warranties.

CONTEXT: Mountain cabin properties in Fannin County, Georgia (Blue Ridge area).
    - Terrain: Steep mountain slopes, variable soil conditions
    - Climate: 4-season (freeze/thaw cycles, heavy rain events)
    - Utilities: Many properties on well water + septic (no municipal)
    - Special: Hot tubs standard, fireplaces common, long gravel driveways
    - Jurisdiction: Fannin County Building Department, Georgia DCA codes

RULES:
1. Classify every document into its engineering discipline and document type.
2. Track all projects through their complete lifecycle (Concept → CO → Closeout).
3. Flag ANY code compliance issue as CRITICAL — no exceptions.
4. Permit expirations within 30 days are HIGH priority alerts.
5. Inspection failures must be tracked to resolution.
6. MEP system age > 15 years triggers a REPLACEMENT_ADVISORY.
7. Septic system issues are ALWAYS CRITICAL (environmental + health).
8. NEVER access or reference Division A (Holding) or Division B (PM) data.
9. Report anomalies immediately — structural, code, or permitting issues.

RESPONSE FORMAT: Always respond with valid JSON.
"""


# =============================================================================
# CORE OPERATIONS
# =============================================================================

def classify_document(
    document: Dict[str, Any],
    classification_rules: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Classify an engineering document by discipline and type.

    Uses learned rules first (skip LLM if we've seen this pattern before),
    then falls back to LLM classification.

    Args:
        document: Document metadata (filepath, filename, extension, etc.)
        classification_rules: Learned pattern→classification mappings

    Returns:
        Enriched document with discipline, doc_type, confidence, reasoning.
    """
    filename = document.get("filename", "UNKNOWN")
    filepath = document.get("file_path", "")
    ext = document.get("extension", "")

    # Check learned rules first (pattern matching on filename)
    if classification_rules:
        for pattern, rule in classification_rules.items():
            if pattern.lower() in filename.lower() or pattern.lower() in filepath.lower():
                logger.info(f"Applied learned rule for pattern '{pattern}': {rule['doc_type']}")
                return {
                    **document,
                    "discipline": rule["discipline"],
                    "doc_type": rule["doc_type"],
                    "confidence": 0.95,
                    "reasoning": f"Learned rule: {rule.get('reasoning', 'previously classified')}",
                    "method": "learned_rule",
                }

    # LLM classification
    prompt = (
        f"Classify this engineering/construction document:\n"
        f"  Filename: {filename}\n"
        f"  Path: {filepath}\n"
        f"  Extension: {ext}\n"
        f"  Size: {document.get('file_size', 'N/A')} bytes\n\n"
        f"Determine the engineering discipline and document type.\n\n"
        f"Respond with JSON: "
        f'{{"discipline": "architectural|civil|structural|mechanical|electrical|'
        f'plumbing|fire_protection|general", '
        f'"doc_type": "...", "confidence": 0.0-1.0, "reasoning": "...", '
        f'"property_name": "..." or null, '
        f'"project_phase": "concept|schematic|dd|cd|permitting|construction|'
        f'inspection|co|closeout" or null}}'
    )

    response = _fast_categorize(prompt, system_role=SYSTEM_PROMPT, temperature=0.15)

    # Strip <think> tags from DeepSeek R1 output
    clean = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL).strip()

    # Extract JSON
    json_match = re.search(r"\{.*\}", clean, flags=re.DOTALL)
    json_str = json_match.group(0) if json_match else clean

    try:
        parsed = json.loads(json_str)
        return {
            **document,
            "discipline": parsed.get("discipline", Discipline.GENERAL),
            "doc_type": parsed.get("doc_type", DocType.UNKNOWN),
            "confidence": parsed.get("confidence", 0.5),
            "reasoning": parsed.get("reasoning", ""),
            "property_name": parsed.get("property_name"),
            "project_phase": parsed.get("project_phase"),
            "method": "llm_classification",
        }
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse LLM response for {filename}: {clean[:200]}")
        return {
            **document,
            "discipline": Discipline.GENERAL,
            "doc_type": DocType.UNKNOWN,
            "confidence": 0.0,
            "reasoning": f"LLM parse failure: {clean[:200]}",
            "method": "failed",
        }


def learn_classification_rule(
    pattern: str,
    discipline: str,
    doc_type: str,
    reasoning: str,
    state: EngineeringAgentState,
) -> EngineeringAgentState:
    """
    Write a permanent document classification rule (self-improvement).
    Next time a document matching this pattern appears, the LLM is skipped.
    """
    state.classification_rules[pattern] = {
        "discipline": discipline,
        "doc_type": doc_type,
        "reasoning": reasoning,
        "learned_at": datetime.now(timezone.utc).isoformat(),
    }
    logger.info(f"Learned classification rule: '{pattern}' → {discipline}/{doc_type}")

    _persist_classification_rules(state.classification_rules)
    return state


def check_compliance(document: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Check a classified document for potential code compliance issues.

    Returns a list of compliance flags (empty if no issues detected).
    """
    issues = []
    doc_type = document.get("doc_type", "")
    discipline = document.get("discipline", "")

    # Septic-related documents are always flagged for review
    if doc_type in (DocType.SEPTIC_PLAN, DocType.PERC_TEST, DocType.SEPTIC_PERMIT):
        issues.append({
            "type": "SEPTIC_REVIEW_REQUIRED",
            "severity": "HIGH",
            "discipline": Discipline.CIVIL,
            "detail": f"Septic document requires county health department review: {doc_type}",
            "document": document.get("filename", ""),
        })

    # Structural calculations need PE stamp verification
    if doc_type in (DocType.STRUCTURAL_CALC, DocType.LOAD_DIAGRAM, DocType.FOUNDATION_PLAN):
        issues.append({
            "type": "PE_STAMP_REQUIRED",
            "severity": "HIGH",
            "discipline": Discipline.STRUCTURAL,
            "detail": f"Structural document requires licensed PE stamp: {doc_type}",
            "document": document.get("filename", ""),
        })

    # Fire protection documents need fire marshal review
    if doc_type in (DocType.FIRE_PROTECTION_PLAN, DocType.FIRE_SPRINKLER):
        issues.append({
            "type": "FIRE_MARSHAL_REVIEW",
            "severity": "HIGH",
            "discipline": Discipline.FIRE_PROTECTION,
            "detail": f"Fire protection plan requires fire marshal approval: {doc_type}",
            "document": document.get("filename", ""),
        })

    return issues


def generate_report(state: EngineeringAgentState) -> Dict[str, Any]:
    """
    Generate an aggregated report for the Sovereign.
    Flows UP to Tier 1 only. Never laterally to other divisions.
    """
    # Count by discipline
    by_discipline = {}
    for doc in state.classified_documents:
        disc = doc.get("discipline", "unknown")
        by_discipline[disc] = by_discipline.get(disc, 0) + 1

    # Count by doc type
    by_doc_type = {}
    for doc in state.classified_documents:
        dt = doc.get("doc_type", "Unknown")
        by_doc_type[dt] = by_doc_type.get(dt, 0) + 1

    # Compliance summary
    critical_issues = [
        i for i in state.compliance_issues if i.get("severity") == "CRITICAL"
    ]
    high_issues = [
        i for i in state.compliance_issues if i.get("severity") == "HIGH"
    ]

    return {
        "division": DIVISION_ID,
        "division_name": DIVISION_NAME,
        "cycle_id": state.cycle_id,
        "timestamp": state.timestamp.isoformat(),
        "metrics": {
            "total_documents": len(state.classified_documents),
            "ambiguous_count": len(state.ambiguous_documents),
            "active_projects": len(state.active_projects),
            "pending_permits": len(state.pending_permits),
            "pending_inspections": len(state.pending_inspections),
            "compliance_critical": len(critical_issues),
            "compliance_high": len(high_issues),
            "classification_rules_count": len(state.classification_rules),
            "mep_properties_tracked": len(state.mep_inventory),
            **state.metrics,
        },
        "by_discipline": by_discipline,
        "by_doc_type": by_doc_type,
        "compliance_issues": state.compliance_issues,
        "anomalies": state.anomalies,
    }


# =============================================================================
# AGENT CLASS (OODA-Integrated)
# =============================================================================

class EngineeringAgent:
    """
    The Architect — Engineering Division Agent.

    Full-suite A/E intelligence: Architectural, Civil, Structural,
    Mechanical (HVAC, Plumbing, Electrical, Fire Protection).

    Wraps all Engineering operations with an OODA loop so that every
    document processing cycle is self-monitoring and self-improving.

    Usage:
        agent = EngineeringAgent()
        result = await agent.run_ooda_cycle(documents=[...])
    """

    def __init__(self):
        self.state = EngineeringAgentState(
            classification_rules=load_classification_rules(),
        )
        self._ooda = None
        logger.info(
            f"EngineeringAgent initialized "
            f"({len(self.state.classification_rules)} learned rules)"
        )

    @property
    def ooda(self):
        """Lazy-initialize the OODA loop."""
        if self._ooda is None:
            from recursive_core.ooda_loop import OODALoop
            self._ooda = OODALoop(
                division=DIVISION_ID,
                observe_fn=self._observe,
                orient_fn=self._orient,
                decide_fn=self._decide,
                act_fn=self._act,
                variance_threshold=5.0,
            )
        return self._ooda

    async def run_ooda_cycle(
        self,
        documents: Optional[List[Dict[str, Any]]] = None,
        project_update: Optional[Dict[str, Any]] = None,
        permit_event: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Run a complete OODA cycle for the Engineering Division.

        Can be triggered by:
            - Document ingestion (documents)
            - Project status update (project_update)
            - Permit event (permit_event)
            - Cron schedule (no args — scans for new documents)

        Returns:
            Cycle result dict.
        """
        import asyncio
        import uuid
        from recursive_core.ooda_loop import OODAEvent

        event = OODAEvent(
            event_id=f"div_eng_{uuid.uuid4().hex[:8]}",
            division=DIVISION_ID,
            observation={
                "injected_documents": documents,
                "project_update": project_update,
                "permit_event": permit_event,
                "trigger": (
                    "document_ingestion" if documents else
                    "project_update" if project_update else
                    "permit_event" if permit_event else
                    "scheduled"
                ),
            },
        )

        result = await asyncio.to_thread(self.ooda.run, event)
        report = generate_report(self.state)

        return {
            "division": DIVISION_ID,
            "event_id": event.event_id,
            "success": result.success,
            "needs_optimization": result.needs_optimization,
            "optimization_reason": result.optimization_reason,
            "documents_processed": len(self.state.classified_documents),
            "ambiguous_count": len(self.state.ambiguous_documents),
            "compliance_issues": len(self.state.compliance_issues),
            "report": report,
        }

    # =========================================================================
    # OODA PHASE HANDLERS
    # =========================================================================

    def _observe(self, event):
        """
        OBSERVE: Ingest raw engineering documents or events.

        Sources:
            1. Injected documents (batch ingestion)
            2. Project status updates
            3. Permit events
            4. Scheduled NAS scan for new files
        """
        injected = event.observation.get("injected_documents")
        project_update = event.observation.get("project_update")
        permit_event = event.observation.get("permit_event")

        if injected:
            raw_docs = injected
            logger.info(f"  OBSERVE: {len(raw_docs)} injected documents")
        elif project_update:
            raw_docs = [project_update]
            logger.info(f"  OBSERVE: Project update received")
        elif permit_event:
            raw_docs = [permit_event]
            logger.info(f"  OBSERVE: Permit event received")
        else:
            raw_docs = self._scan_for_new_documents()
            logger.info(f"  OBSERVE: {len(raw_docs)} new documents from NAS scan")

        event.observation["raw_documents"] = raw_docs
        event.observation["count"] = len(raw_docs)
        self.state.pending_documents = raw_docs
        return event

    def _orient(self, event):
        """
        ORIENT: Classify documents by discipline and type.

        Each document is run through the LLM classifier (or matched
        against learned rules). Compliance checks are applied to
        every classified document.
        """
        raw_docs = event.observation.get("raw_documents", [])
        classified = []
        ambiguous = []
        compliance_flags = []
        total_variance = 0.0
        variance_count = 0

        for doc in raw_docs:
            result = classify_document(doc, self.state.classification_rules)
            confidence = result.get("confidence", 0)

            if result.get("doc_type") == DocType.UNKNOWN or confidence < 0.7:
                ambiguous.append(result)
                # Learn moderate-confidence classifications
                if confidence >= 0.5 and result.get("doc_type") != DocType.UNKNOWN:
                    pattern = self._extract_learning_pattern(result)
                    if pattern:
                        learn_classification_rule(
                            pattern=pattern,
                            discipline=result["discipline"],
                            doc_type=result["doc_type"],
                            reasoning=result.get("reasoning", "auto-learned"),
                            state=self.state,
                        )
            else:
                classified.append(result)
                # Run compliance check on every classified document
                issues = check_compliance(result)
                if issues:
                    compliance_flags.extend(issues)

                # Learn high-confidence classifications
                if confidence >= 0.9 and result.get("method") == "llm_classification":
                    pattern = self._extract_learning_pattern(result)
                    if pattern:
                        learn_classification_rule(
                            pattern=pattern,
                            discipline=result["discipline"],
                            doc_type=result["doc_type"],
                            reasoning=result.get("reasoning", "high-confidence classification"),
                            state=self.state,
                        )

            # Variance tracking (if we had predictions)
            predicted = doc.get("predicted_type")
            actual = result.get("doc_type", "")
            if predicted is not None and predicted != actual:
                total_variance += 100.0
                variance_count += 1
            elif predicted is not None:
                variance_count += 1

        self.state.classified_documents.extend(classified)
        self.state.ambiguous_documents.extend(ambiguous)
        self.state.compliance_issues.extend(compliance_flags)

        event.orientation = {
            "classified": len(classified),
            "ambiguous": len(ambiguous),
            "compliance_flags": len(compliance_flags),
            "total_processed": len(raw_docs),
        }

        if variance_count > 0:
            event.variance_pct = total_variance / variance_count
        event.predicted_value = variance_count
        event.actual_value = float(len(classified))

        return event

    def _decide(self, event):
        """
        DECIDE: Determine actions based on classification results.
        """
        classified_count = event.orientation.get("classified", 0)
        ambiguous_count = event.orientation.get("ambiguous", 0)
        compliance_count = event.orientation.get("compliance_flags", 0)

        actions = []
        if classified_count > 0:
            actions.append({"action": "persist_to_registry", "count": classified_count})
        if ambiguous_count > 0:
            actions.append({"action": "flag_for_review", "count": ambiguous_count})
            self.state.anomalies.append({
                "type": "UNCLASSIFIED_DOCUMENTS",
                "count": ambiguous_count,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        if compliance_count > 0:
            actions.append({"action": "escalate_compliance", "count": compliance_count})
            # Compliance issues are ALWAYS anomalies
            self.state.anomalies.append({
                "type": "COMPLIANCE_FLAGS",
                "severity": "HIGH",
                "count": compliance_count,
                "detail": "Engineering compliance issues detected",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        event.decision = {
            "action": "classify_persist_comply",
            "sub_actions": actions,
        }
        return event

    def _act(self, event):
        """
        ACT: Persist classified documents and process compliance alerts.
        """
        success_count = 0
        error_count = 0

        for doc in self.state.classified_documents:
            try:
                if self._insert_document(doc):
                    success_count += 1
                else:
                    error_count += 1
            except Exception as e:
                logger.error(f"Failed to persist document: {e}")
                error_count += 1

        event.action_result = {
            "success": error_count == 0,
            "persisted": success_count,
            "errors": error_count,
            "compliance_issues": len(self.state.compliance_issues),
        }

        if error_count > 0:
            event.action_result["error"] = f"{error_count} documents failed to persist"

        logger.info(
            f"  ACT: Persisted {success_count}/{success_count + error_count} documents "
            f"| {len(self.state.compliance_issues)} compliance flags"
        )
        return event

    # =========================================================================
    # DATABASE OPERATIONS
    # =========================================================================

    def _insert_document(self, doc: Dict[str, Any]) -> bool:
        """Insert a classified document into the engineering registry."""
        try:
            import psycopg2
            from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
            conn = psycopg2.connect(
                host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                user=DB_USER, password=DB_PASSWORD,
            )
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO engineering.drawings
                        (property_id, project_id, discipline, doc_type,
                         file_path, filename, extension, file_size,
                         sheet_number, title, confidence, ai_json, phase)
                    VALUES (
                        (SELECT id FROM properties WHERE name = %s LIMIT 1),
                        NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1
                    )
                    ON CONFLICT (file_path) DO UPDATE SET
                        discipline = EXCLUDED.discipline,
                        doc_type = EXCLUDED.doc_type,
                        confidence = EXCLUDED.confidence,
                        ai_json = EXCLUDED.ai_json
                """, (
                    doc.get("property_name"),
                    doc.get("discipline", "general"),
                    doc.get("doc_type", "Unknown"),
                    doc.get("file_path"),
                    doc.get("filename"),
                    doc.get("extension"),
                    doc.get("file_size", 0),
                    doc.get("sheet_number"),
                    doc.get("title"),
                    doc.get("confidence", 0),
                    json.dumps({
                        "reasoning": doc.get("reasoning", ""),
                        "method": doc.get("method", ""),
                        "project_phase": doc.get("project_phase"),
                    }),
                ))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Engineering insert failed: {e}")
            return False

    # =========================================================================
    # NAS DOCUMENT SCANNING
    # =========================================================================

    def _scan_for_new_documents(self) -> List[Dict[str, Any]]:
        """Scan NAS for new engineering documents not yet in the registry."""
        import os

        scan_dirs = [
            "/mnt/fortress_nas/Enterprise_War_Room/Engineering",
            "/mnt/fortress_nas/Enterprise_War_Room/Construction",
            "/mnt/fortress_nas/Enterprise_War_Room/Blueprints",
            "/mnt/fortress_nas/Enterprise_War_Room/Permits",
        ]

        engineering_extensions = {
            ".pdf", ".dwg", ".dxf", ".dgn",          # Drawings
            ".jpg", ".jpeg", ".png", ".tiff", ".tif",  # Scanned plans
            ".doc", ".docx", ".xlsx", ".xls",          # Specs & reports
            ".rvt", ".ifc", ".step", ".stp",           # BIM / CAD
        }

        new_docs = []
        for scan_dir in scan_dirs:
            if not os.path.isdir(scan_dir):
                continue
            for root, _, files in os.walk(scan_dir):
                for f in files:
                    if f.startswith("."):
                        continue
                    ext = os.path.splitext(f)[1].lower()
                    if ext not in engineering_extensions:
                        continue
                    filepath = os.path.join(root, f)
                    try:
                        fsize = os.path.getsize(filepath)
                    except OSError:
                        fsize = 0
                    new_docs.append({
                        "file_path": filepath,
                        "filename": f,
                        "extension": ext,
                        "file_size": fsize,
                    })

        return new_docs

    # =========================================================================
    # LEARNING HELPERS
    # =========================================================================

    @staticmethod
    def _extract_learning_pattern(doc: Dict[str, Any]) -> Optional[str]:
        """
        Extract a reusable pattern from a document for learning.
        Uses the most distinctive part of the filename.
        """
        filename = doc.get("filename", "")
        # Remove extension and common noise
        base = re.sub(r'\.[^.]+$', '', filename)
        base = re.sub(r'[\d_\-\.]+', ' ', base).strip()

        # Use the longest meaningful word as the pattern
        words = [w for w in base.split() if len(w) >= 4]
        if words:
            return max(words, key=len).lower()
        return None


# =============================================================================
# PERSISTENCE
# =============================================================================

def _persist_classification_rules(rules: Dict[str, Dict[str, str]]) -> None:
    """Save learned classification rules to NAS (or local fallback)."""
    try:
        from src.fortress_paths import paths
        rules_path = paths.base_dir / "division_engineering" / "classification_rules.json"
    except ImportError:
        from pathlib import Path
        rules_path = Path("data/division_engineering/classification_rules.json")

    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(json.dumps(rules, indent=2, default=str), encoding="utf-8")
    logger.info(f"Persisted {len(rules)} classification rules to {rules_path}")


def load_classification_rules() -> Dict[str, Dict[str, str]]:
    """Load previously learned classification rules."""
    try:
        from src.fortress_paths import paths
        rules_path = paths.base_dir / "division_engineering" / "classification_rules.json"
    except ImportError:
        from pathlib import Path
        rules_path = Path("data/division_engineering/classification_rules.json")

    if rules_path.exists():
        return json.loads(rules_path.read_text(encoding="utf-8"))
    return {}
