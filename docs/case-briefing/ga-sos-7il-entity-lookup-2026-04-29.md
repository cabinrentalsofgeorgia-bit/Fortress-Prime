# GA SoS Entity Lookup — 7 IL Properties (2026-04-29)

**Track A §4.4 deliverable.**
**Status:** ⚠️ Automated lookup blocked. Operator manual lookup required to fully resolve Q8 (name reversal).

---

## What was attempted

Direct query of the Georgia Corporations Division for both:

1. **7 IL Properties, LLC**
2. **7 IL Properties of Georgia, LLC**

Endpoints exercised:

| Endpoint | Result |
|---|---|
| `https://ecorp.sos.ga.gov/businesssearch?searchText=7+IL+Properties` | HTTP 403, Cloudflare `cf-mitigated: challenge` (interactive browser challenge) |
| `https://ecorp.sos.ga.gov/Account/LogOn` | HTTP 403, same challenge |
| `https://ecorp.sos.ga.gov/api/businesssearch` (POST JSON) | Cloudflare interstitial, no JSON response |
| `https://opencorporates.com/companies?q=7+IL+Properties&jurisdiction_code=us_ga` | HAProxy human-verification challenge |
| `https://www.bizapedia.com/ga/7-il-properties-llc.html` | Bizapedia human-verification page |

All public/free entity-search endpoints sit behind Cloudflare or equivalent bot-protection layers that require an interactive browser challenge. Automated WebFetch from the Fortress sovereign environment cannot complete the challenge. The §6 hard constraint authorizes the GA SoS lookup specifically as the only permitted outbound HTTP call, but it does not provide a path through the bot-protection layer.

## What we already know from the case record

| Fact | Source |
|---|---|
| **7 IL Properties, LLC** is identified as a **Colorado LLC** (not Georgia-domiciled) in the operative Case II Complaint | `Complaint_7IL_v_Knight_James_NDGA-II.pdf`, ¶ 1 |
| Plaintiff's principal place of business: **503 North Main, Suite 429, Pueblo, CO 81003** | Complaint ¶ 1 |
| Diversity assertion: "No member of Plaintiff is a citizen of the State of Georgia" | Complaint ¶ 1 |
| Plaintiff principal: **John Thatcher** (per 2021 + 2025 inspection reports' "Prepared For" field) | DRAFT brief §1 |
| **7 IL Properties of Georgia, LLC** — no curated-set evidence of this entity name; not referenced in Complaint, Case I trial record, or curated emails | absence in the curated set |

The case-record-only view is **consistent with the Colorado-only entity hypothesis**: 7 IL Properties LLC is a Colorado LLC and no contemporary filing references a Georgia-formation entity with the same or reversed name.

## Implications for Q8 (name-reversal hypothesis)

Three possibilities the operator's manual SoS lookup must distinguish between:

1. **Same entity.** "7 IL Properties of Georgia, LLC" was an alternate registered name (Georgia foreign-LLC certificate of authority) for the Colorado parent.
2. **Different entities.** A separately-formed Georgia LLC under that name exists and is unrelated.
3. **One withdrawn.** Either name was filed in Georgia and then withdrawn / dissolved / administratively dissolved before the 2025 transactions — supporting (and timestamping) a strategic re-styling.

Each of these matters in different ways for the breach / slander-of-title / quiet-title claims; the reversed-name hypothesis is most directly probative if (3) is the answer with a recent-pre-2025 withdrawal.

## Recommended next step (operator)

Manually execute these two queries from a browser (the Cloudflare challenge resolves with one click):

1. https://ecorp.sos.ga.gov/BusinessSearch — search "7 IL Properties"
2. Same search portal — search "7 IL Properties of Georgia"

For each hit captured, record:

* Control number
* Status (active / inactive / withdrawn / dissolved / admin-dissolved)
* Formation/registration date
* Registered agent name + address
* Principal office address
* Member/officer information (if shown on the entity detail page)
* Annual registration history (most recent filing date)

Drop the screenshots / printouts into `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii/work-product/ga-sos-lookup-2026-04-29/` and update the §3.1 plaintiff record + the Section 6 evidentiary inventory.

## Summary line (for Track A closing report)

> **Same entity / different entities / one withdrawn:** UNDETERMINED — automated lookup blocked by Cloudflare challenge. Case record supports a Colorado-only hypothesis (Complaint ¶ 1). Operator manual lookup required.
