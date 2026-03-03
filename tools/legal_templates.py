#!/usr/bin/env python3
"""
FORTRESS PRIME — Legal Document Template Engine
==================================================
Template-driven generation of court filings, formal correspondence, and legal
documents. All templates use Python string formatting populated from case data.

Templates:
    - court_caption          Standard Georgia Superior Court caption block
    - motion_extension       Motion for Extension of Time to File Answer
    - answer_complaint       Answer to Complaint with affirmative defenses
    - demand_letter          Formal demand/response letter to opposing counsel
    - correspondence_formal  General formal legal correspondence
    - certificate_of_service Certificate of Service block

Usage:
    from tools.legal_templates import render_template, list_templates

    doc = render_template("motion_extension", case_data, overrides={...})
    # doc is a plain-text string ready to save to NAS or push to Gmail

Architecture:
    Templates are pure-text generators. No LLM needed — formal legal docs
    follow strict formats. Data comes from legal.cases + legal.correspondence.
"""

import hashlib
from datetime import datetime, date, timezone
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════════
# TEMPLATE REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

TEMPLATES = {}


def register(name: str):
    """Decorator to register a template function."""
    def wrapper(fn):
        TEMPLATES[name] = fn
        return fn
    return wrapper


def list_templates() -> list:
    """Return list of available template names with descriptions."""
    return [
        {"name": name, "description": fn.__doc__.strip().split("\n")[0] if fn.__doc__ else name}
        for name, fn in TEMPLATES.items()
    ]


def render_template(name: str, case: dict, overrides: dict = None) -> str:
    """
    Render a legal document template with case data.

    Args:
        name: Template name (e.g., 'motion_extension')
        case: Dict from legal.cases row (all columns)
        overrides: Optional dict to override/supplement case fields

    Returns:
        Rendered document as plain text string
    """
    if name not in TEMPLATES:
        raise ValueError(f"Unknown template: {name}. Available: {list(TEMPLATES.keys())}")

    ctx = dict(case)
    if overrides:
        ctx.update(overrides)

    # Standard context enrichment
    ctx.setdefault("today_date", date.today().strftime("%B %d, %Y"))
    ctx.setdefault("today_iso", date.today().isoformat())
    ctx.setdefault("generated_at", datetime.now(timezone.utc).isoformat())

    return TEMPLATES[name](ctx)


def hash_document(text: str) -> str:
    """Generate SHA-256 hash for tamper-proofing."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER: Parse structured fields from case record
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_opposing_counsel(case: dict) -> dict:
    """Parse opposing_counsel text field into structured components."""
    oc = case.get("opposing_counsel", "") or ""
    parts = [p.strip() for p in oc.split(",")]
    return {
        "oc_name": parts[0] if len(parts) > 0 else "Opposing Counsel",
        "oc_firm": parts[1] if len(parts) > 1 else "",
        "oc_address": ", ".join(parts[2:4]) if len(parts) > 3 else "",
        "oc_phone": parts[4] if len(parts) > 4 else "",
        "oc_email": parts[5] if len(parts) > 5 else "",
        "oc_bar": parts[6] if len(parts) > 6 else "",
    }


def _get_defendant_info(case: dict) -> dict:
    """Extract defendant info from case notes or defaults."""
    notes = case.get("notes", "") or ""
    return {
        "def_name": "Cabin Rentals of Georgia, LLC",
        "def_ra": "Gary M. Knight",
        "def_ra_title": "Sole Owner, Registered Agent and Managing Member",
        "def_address": "PO Box 982, Morganton, GA 30560",
        "def_phone": "(678) 549-3680",
        "def_email": "info@cabin-rentals-of-georgia.com",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# TEMPLATE: Court Caption
# ═══════════════════════════════════════════════════════════════════════════════

@register("court_caption")
def tmpl_court_caption(ctx: dict) -> str:
    """Standard Georgia Superior Court case caption block."""
    court = ctx.get("court", "Superior Court of Fannin County, State of Georgia")
    plaintiff = ctx.get("plan_admin", "Plaintiff")
    defendant = ctx.get("def_name", "Cabin Rentals of Georgia, LLC")
    case_number = ctx.get("case_number", "")
    our_role = ctx.get("our_role", "defendant")

    if our_role == "defendant":
        top_party = plaintiff
        top_label = "Plaintiff"
        bottom_party = defendant
        bottom_label = "Defendant"
    else:
        top_party = defendant
        top_label = "Plaintiff"
        bottom_party = plaintiff
        bottom_label = "Defendant"

    return f"""IN THE {court.upper()}

{top_party.upper()}
    {top_label},

v.                                               Civil Action No. {case_number}

{bottom_party.upper()}
    {bottom_label}.
"""


# ═══════════════════════════════════════════════════════════════════════════════
# TEMPLATE: Motion for Extension of Time
# ═══════════════════════════════════════════════════════════════════════════════

@register("motion_extension")
def tmpl_motion_extension(ctx: dict) -> str:
    """Motion for Extension of Time to File Answer (Georgia Superior Court format)."""
    oc = _parse_opposing_counsel(ctx)
    d = _get_defendant_info(ctx)
    caption = tmpl_court_caption(ctx)
    case_number = ctx.get("case_number", "")
    today = ctx.get("today_date", date.today().strftime("%B %d, %Y"))

    original_deadline = ctx.get("original_deadline", ctx.get("critical_date", ""))
    if isinstance(original_deadline, date):
        original_deadline = original_deadline.strftime("%B %d, %Y")

    extension_days = int(ctx.get("extension_days", 30))
    proposed_deadline = ctx.get("proposed_deadline", "")
    service_date = ctx.get("service_date", "")
    service_method = ctx.get("service_method", "personal service")
    reason = ctx.get("extension_reason",
        "Defendant needs additional time to locate, review, and analyze the "
        "underlying contractual documents, account statements, and correspondence "
        "to prepare a proper and responsive Answer.")

    return f"""{caption}
DEFENDANT'S MOTION FOR EXTENSION OF TIME TO FILE ANSWER

COMES NOW Defendant, {d['def_name']}, acting through its authorized
representative {d['def_ra']} ({d['def_ra_title']}), and pursuant to
O.C.G.A. Section 9-11-6(b), respectfully moves this Court for an extension
of time within which to file its Answer to Plaintiff's Complaint, and in
support thereof shows the Court the following:

I. PROCEDURAL HISTORY

1. Plaintiff filed its Complaint in this action on or about
   {ctx.get('petition_date', '[DATE]')}.

2. Defendant was served with the Summons and Complaint on {service_date},
   through {service_method} upon {d['def_ra']}, Registered Agent for
   {d['def_name']}, at {d['def_address']}.

3. Pursuant to O.C.G.A. Section 9-11-12(a), Defendant's Answer was due
   within thirty (30) days of service, making the original deadline
   {original_deadline}.

II. GROUNDS FOR EXTENSION

4. Defendant respectfully requests an extension of time for good cause
   shown, as follows:

   a. COMPLEXITY OF CLAIMS AND NEED FOR INVESTIGATION. {reason}

   b. NEED TO REVIEW FINANCIAL RECORDS. The amounts claimed by Plaintiff
      require careful reconciliation against Defendant's internal financial
      records.

   c. EVALUATION OF POTENTIAL DEFENSES AND COUNTERCLAIMS. Defendant
      requires additional time to evaluate potential defenses.

   d. RETENTION OF COUNSEL. Defendant is in the process of evaluating
      whether to retain legal counsel to represent its interests.

   e. NO PREJUDICE TO PLAINTIFF. Granting this extension will cause no
      prejudice to Plaintiff, as the matter is in its earliest stages.

III. REQUEST

5. WHEREFORE, Defendant respectfully requests that this Court enter an
   Order granting Defendant an extension of {extension_days} additional days,
   up to and including {proposed_deadline}, within which to file its Answer.

6. This is Defendant's first request for an extension and is made in good
   faith and not for the purpose of delay.

IV. CERTIFICATE OF SERVICE

I hereby certify that I have served a true and correct copy of this Motion
upon Plaintiff's counsel of record:

    {oc['oc_name']}
    {oc['oc_firm']}
    {oc['oc_address']}
    {oc['oc_email']}

by depositing same in the United States Mail, postage prepaid, and/or by
electronic transmission on this {today}.

Respectfully submitted,

____________________________________
{d['def_ra']}
{d['def_ra_title']}
{d['def_name']}
{d['def_address']}
Telephone: {d['def_phone']}
Email: {d['def_email']}


PROPOSED ORDER

{caption}
ORDER

The above-styled Motion for Extension of Time having come before this
Court, and good cause having been shown:

IT IS HEREBY ORDERED that Defendant's time to file its Answer to
Plaintiff's Complaint is extended to and including {proposed_deadline}.

SO ORDERED this ___ day of _____________, {date.today().year}.

____________________________________
Judge, {ctx.get('court', 'Superior Court')}

---
Document generated: {ctx.get('generated_at', '')}
Integrity hash: {{hash}}
Case Reference: Fortress Prime Legal CRM
"""


# ═══════════════════════════════════════════════════════════════════════════════
# TEMPLATE: Formal Correspondence to Opposing Counsel
# ═══════════════════════════════════════════════════════════════════════════════

@register("correspondence_formal")
def tmpl_correspondence_formal(ctx: dict) -> str:
    """Formal letter to opposing counsel (demand, response, or general)."""
    oc = _parse_opposing_counsel(ctx)
    d = _get_defendant_info(ctx)
    today = ctx.get("today_date", date.today().strftime("%B %d, %Y"))

    subject_line = ctx.get("subject", f"Re: {ctx.get('case_name', 'Case')} — {ctx.get('case_number', '')}")
    body_text = ctx.get("body", "[BODY TEXT — describe the purpose of this correspondence]")

    return f"""{today}

VIA EMAIL AND U.S. MAIL

{oc['oc_name']}
{oc['oc_firm']}
{oc['oc_address']}
{oc['oc_email']}

    Re: {subject_line}
        Civil Action No. {ctx.get('case_number', '')}
        {ctx.get('court', '')}

Dear {oc['oc_name']}:

{body_text}

Please direct all future correspondence regarding this matter to the
undersigned at the address below.

Respectfully,

____________________________________
{d['def_ra']}
{d['def_ra_title']}
{d['def_name']}
{d['def_address']}
Telephone: {d['def_phone']}
Email: {d['def_email']}

---
Document generated: {ctx.get('generated_at', '')}
Case Reference: Fortress Prime Legal CRM
"""


# ═══════════════════════════════════════════════════════════════════════════════
# TEMPLATE: Demand Letter / Settlement Offer
# ═══════════════════════════════════════════════════════════════════════════════

@register("demand_letter")
def tmpl_demand_letter(ctx: dict) -> str:
    """Formal demand letter or settlement offer to opposing counsel."""
    oc = _parse_opposing_counsel(ctx)
    d = _get_defendant_info(ctx)
    today = ctx.get("today_date", date.today().strftime("%B %d, %Y"))

    settlement_amount = ctx.get("settlement_amount", "[AMOUNT]")
    settlement_terms = ctx.get("settlement_terms",
        "full and final settlement of all claims, with mutual releases and "
        "dismissal of the above-captioned action with prejudice")
    response_deadline = ctx.get("response_deadline", "fourteen (14) days")

    return f"""{today}

VIA EMAIL AND U.S. MAIL
SETTLEMENT COMMUNICATION — CONFIDENTIAL
(Subject to Fed. R. Evid. 408 / O.C.G.A. Section 24-4-408)

{oc['oc_name']}
{oc['oc_firm']}
{oc['oc_address']}
{oc['oc_email']}

    Re: {ctx.get('case_name', '')}
        Civil Action No. {ctx.get('case_number', '')}
        {ctx.get('court', '')}

Dear {oc['oc_name']}:

I write on behalf of {d['def_name']} regarding the above-captioned matter.

In the interest of resolving this matter without further expenditure of
time and resources by both parties, my client is prepared to offer
${settlement_amount} as {settlement_terms}.

This offer is contingent upon acceptance within {response_deadline} of
the date of this letter and is made without any admission of liability.

This communication is made for settlement purposes only and is subject to
the protections of O.C.G.A. Section 24-4-408 and Federal Rule of Evidence
408. It shall not be admissible in any proceeding for any purpose other
than to prove the existence and terms of a settlement agreement, if one
is reached.

Please contact the undersigned to discuss this matter further.

Respectfully,

____________________________________
{d['def_ra']}
{d['def_ra_title']}
{d['def_name']}
{d['def_address']}
Telephone: {d['def_phone']}
Email: {d['def_email']}

---
CONFIDENTIAL SETTLEMENT COMMUNICATION
Document generated: {ctx.get('generated_at', '')}
Case Reference: Fortress Prime Legal CRM
"""


# ═══════════════════════════════════════════════════════════════════════════════
# TEMPLATE: Certificate of Service (standalone)
# ═══════════════════════════════════════════════════════════════════════════════

@register("certificate_of_service")
def tmpl_certificate_of_service(ctx: dict) -> str:
    """Standalone Certificate of Service for any filing."""
    oc = _parse_opposing_counsel(ctx)
    d = _get_defendant_info(ctx)
    today = ctx.get("today_date", date.today().strftime("%B %d, %Y"))
    document_name = ctx.get("document_name", "the foregoing document")

    return f"""CERTIFICATE OF SERVICE

I hereby certify that I have served a true and correct copy of
{document_name} upon Plaintiff's counsel of record at the following
address:

    {oc['oc_name']}
    {oc['oc_firm']}
    {oc['oc_address']}
    {oc['oc_email']}
    {oc['oc_bar']}

by depositing same in the United States Mail, postage prepaid, and/or by
electronic transmission on this {today}.

____________________________________
{d['def_ra']}
{d['def_name']}
"""


# ═══════════════════════════════════════════════════════════════════════════════
# TEMPLATE: Email to Opposing Counsel (Gmail draft format)
# ═══════════════════════════════════════════════════════════════════════════════

@register("email_opposing_counsel")
def tmpl_email_opposing_counsel(ctx: dict) -> str:
    """Formal email to opposing counsel (for Gmail draft creation)."""
    oc = _parse_opposing_counsel(ctx)
    d = _get_defendant_info(ctx)
    case_number = ctx.get("case_number", "")
    case_name = ctx.get("case_name", "")
    body_text = ctx.get("body",
        "I am writing regarding the above-referenced matter. "
        "Please contact me at your earliest convenience to discuss.")

    return f"""Dear {oc['oc_name']},

Re: {case_name}
    Civil Action No. {case_number}

{body_text}

Respectfully,

{d['def_ra']}
{d['def_ra_title']}
{d['def_name']}
{d['def_address']}
Tel: {d['def_phone']}
Email: {d['def_email']}
"""


# ═══════════════════════════════════════════════════════════════════════════════
# TEMPLATE: Answer to Complaint (framework)
# ═══════════════════════════════════════════════════════════════════════════════

@register("answer_complaint")
def tmpl_answer_complaint(ctx: dict) -> str:
    """Answer to Complaint with affirmative defenses (Georgia Superior Court)."""
    oc = _parse_opposing_counsel(ctx)
    d = _get_defendant_info(ctx)
    caption = tmpl_court_caption(ctx)
    today = ctx.get("today_date", date.today().strftime("%B %d, %Y"))
    claim_basis = ctx.get("our_claim_basis", "") or ""

    # Build case-aware defense descriptions
    default_defenses = [
        ("Failure to State a Claim",
         "Plaintiff's Complaint fails to state a claim upon which relief can "
         "be granted and should be dismissed pursuant to O.C.G.A. Section 9-11-12(b)(6)."),
        ("Disputed Account / No Assent",
         "Defendant disputes the balance alleged by Plaintiff. The account "
         "statements attached to the Complaint have not been verified against "
         "Defendant's internal records and Defendant did not assent to the "
         "stated balances."),
        ("Lack of Authority / Unauthorized Contract Modification",
         "Upon information and belief, the updated Compensation Schedule "
         "(Exhibit B to the Complaint) was signed by Colleen Blackman, who "
         "was not an authorized agent, officer, or managing member of Cabin "
         "Rentals of Georgia, LLC, and lacked authority to bind Defendant to "
         "modified contractual terms."),
        ("Payment / Set-Off / Recoupment",
         "Defendant has made payments toward the amounts at issue, including "
         "but not limited to documented payments that reduced the balance. "
         "Defendant reserves the right to assert set-off and recoupment for "
         "any overpayments or amounts owed by Plaintiff to Defendant."),
        ("Failure to Mitigate",
         "Plaintiff failed to mitigate its alleged damages by continuing to "
         "issue invoices and accumulate charges despite knowledge of the "
         "dispute and without taking reasonable steps to resolve the matter."),
        ("Inaccurate Accounting",
         "Plaintiff's account statement contains discrepancies. Defendant "
         "requires discovery to reconcile Plaintiff's invoices against "
         "Defendant's internal Streamline booking records and payment history."),
        ("No Attorney's Fees / Not Stubbornly Litigious",
         "Plaintiff's claim for attorney's fees under O.C.G.A. Section 13-6-11 "
         "should be denied. Defendant has not been stubbornly litigious or "
         "caused unnecessary trouble and expense. The dispute involves "
         "legitimate questions of contract authorization and account accuracy."),
        ("Statute of Limitations",
         "Some or all of Plaintiff's claims are barred, in whole or in part, "
         "by the applicable statute of limitations. The account statement "
         "reflects invoices dating back to November 2019. Under O.C.G.A. "
         "Section 9-3-25, open account claims are subject to a four-year "
         "limitation period."),
        ("Reservation of Defenses",
         "Defendant reserves the right to assert additional affirmative "
         "defenses as may become apparent during discovery."),
    ]

    defenses = ctx.get("affirmative_defenses_detailed", default_defenses)

    defense_text = ""
    ordinals = ["FIRST", "SECOND", "THIRD", "FOURTH", "FIFTH", "SIXTH",
                 "SEVENTH", "EIGHTH", "NINTH", "TENTH", "ELEVENTH", "TWELFTH"]
    for i, defense in enumerate(defenses, 1):
        if isinstance(defense, tuple):
            d_name, d_desc = defense
        else:
            d_name = defense
            d_desc = "[Description of defense to be completed by counsel]"
        ordinal = ordinals[i-1] if i <= len(ordinals) else f"{i}TH"
        defense_text += f"""
{ordinal} DEFENSE -- {d_name.upper()}
{d_desc}

"""

    return f"""{caption}
DEFENDANT'S ANSWER AND DEFENSES

COMES NOW Defendant, {d['def_name']} ("CROG" or "Defendant"), acting
through its authorized representative {d['def_ra']} ({d['def_ra_title']}),
and files this Answer to Plaintiff's Complaint, and respectfully shows
this Court the following:

JURISDICTIONAL ALLEGATIONS

1. Defendant admits that this Court has jurisdiction over this action and
   that venue is proper in Fannin County, Georgia.

2. Defendant admits that it is a Georgia limited liability company with
   its principal place of business in Fannin County, Georgia.

RESPONSE TO COUNT I -- ACCOUNT STATED

3. Defendant admits that it entered into a business relationship with
   Plaintiff (formerly CSA Travel Protection) relating to travel
   insurance products.

4. Defendant denies that an "account stated" exists as alleged. Defendant
   did not assent to the balances reflected on Plaintiff's account
   statements and disputes the accuracy of the amounts claimed.

5. Defendant denies that it owes the sum of $7,500.00 or any other
   amount as alleged in Count I.

RESPONSE TO COUNT II -- BREACH OF CONTRACT

6. Defendant admits that a Vacation Rental Participation Agreement was
   executed on or about August 14, 2018.

7. Defendant denies that the "updated Compensation Schedule" (Exhibit B)
   constitutes a valid modification to the Agreement. Upon information
   and belief, Colleen Blackman, the purported signatory of Exhibit B,
   was not an authorized representative of Defendant and lacked
   authority to bind Defendant to modified terms.

8. Defendant denies that it breached the Agreement as alleged and denies
   that Plaintiff is entitled to the relief requested.

9. Defendant denies each and every allegation not specifically admitted
   herein.

AFFIRMATIVE DEFENSES

Defendant asserts the following affirmative defenses, without waiving any
other defenses that may become apparent during discovery:

{defense_text}

PRAYER FOR RELIEF

WHEREFORE, Defendant respectfully prays:

a. That Plaintiff's Complaint be dismissed in its entirety;
b. That Plaintiff take nothing by its Complaint;
c. That Defendant be awarded its costs of defense;
d. That Defendant be awarded its attorney's fees to the extent permitted
   by law;
e. For such other and further relief as this Court deems just and proper.

JURY TRIAL DEMAND

Defendant hereby demands a trial by jury on all issues so triable.

Respectfully submitted this {today}.

____________________________________
{d['def_ra']}
{d['def_ra_title']}
{d['def_name']}
{d['def_address']}
Telephone: {d['def_phone']}
Email: {d['def_email']}

CERTIFICATE OF SERVICE

I hereby certify that I have served a true and correct copy of the
foregoing Answer upon Plaintiff's counsel of record:

    {oc['oc_name']}
    {oc['oc_firm']}
    {oc['oc_address']}
    {oc['oc_email']}

by depositing same in the United States Mail, postage prepaid, and/or by
electronic transmission on this {today}.

____________________________________
{d['def_ra']}

---
Document generated: {ctx.get('generated_at', '')}
Integrity hash: {{hash}}
Case Reference: Fortress Prime Legal CRM
"""


# ═══════════════════════════════════════════════════════════════════════════════
# TEMPLATE: Attorney Briefing Summary
# ═══════════════════════════════════════════════════════════════════════════════

@register("attorney_briefing")
def tmpl_attorney_briefing(ctx: dict) -> str:
    """Attorney briefing summary with case facts and evidence inventory."""
    case_number = ctx.get("case_number", "")
    case_name = ctx.get("case_name", "")
    court = ctx.get("court", "")
    our_role = ctx.get("our_role", "")
    claim_basis = ctx.get("our_claim_basis", "")
    oc = _parse_opposing_counsel(ctx)
    critical_date = ctx.get("critical_date", "")
    critical_note = ctx.get("critical_note", "")
    notes = ctx.get("notes", "")
    evidence_count = ctx.get("evidence_count", 0)
    action_count = ctx.get("pending_actions", 0)
    today = ctx.get("today_date", date.today().strftime("%B %d, %Y"))

    return f"""ATTORNEY BRIEFING PACKAGE
========================
{case_name}
Civil Action No. {case_number}

Prepared: {today}
Classification: PRIVILEGED AND CONFIDENTIAL -- WORK PRODUCT

CASE OVERVIEW
-------------
Court:          {court}
Our Role:       {our_role}
Critical Date:  {critical_date}
Critical Note:  {critical_note}

CLAIMS SUMMARY
--------------
{claim_basis}

OPPOSING COUNSEL
----------------
{oc['oc_name']}
{oc['oc_firm']}
{oc['oc_address']}
{oc['oc_email']}
{oc['oc_bar']}

CASE NOTES
----------
{notes}

EVIDENCE INVENTORY
------------------
Total evidence items indexed: {evidence_count}
Pending action items: {action_count}

Documents are stored at:
/mnt/fortress_nas/sectors/legal/{ctx.get('case_slug', '')}/

---
Generated by Fortress Prime Legal CRM
{ctx.get('generated_at', '')}
"""
