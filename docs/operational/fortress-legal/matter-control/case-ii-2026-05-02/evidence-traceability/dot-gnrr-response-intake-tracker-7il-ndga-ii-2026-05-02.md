# DOT / GNRR Response Intake Tracker - 7IL Case II

Date: 2026-05-02
Classification: Repo-safe intake tracker. Does not include privileged email substance, private contact details, or unsent legal-demand posture.
Operator service status: Gary Knight has not been served as of 2026-05-02.

This is not a filing and not legal advice. It is the intake control layer for responses to the DOT / GNRR records-request packet.

## Control Purpose

The DOT / GNRR records-request packet creates request text. This tracker controls what happens after the operator or counsel sends any request:

1. no response is treated as evidence until it has a source path and SHA256 hash;
2. no response is treated as a legal conclusion without counsel verification;
3. public records and privileged analysis stay separated;
4. each response is mapped back to the easement validity map, GNRR comparison, issue matrix, and evidence-gap list.

## Intake Paths

| Lane | NAS Path | Use |
|---|---|---|
| GDOT open-records responses | `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii/incoming/dot-gnrr-records-request-20260502/gdot-open-records/` | Public agency responses, production files, fee estimates, no-records replies, and correspondence. |
| GNRR / Blue Ridge responses | `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii/incoming/dot-gnrr-records-request-20260502/gnrr-blue-ridge/` | Private railroad/operator responses if counsel/operator chooses to send the inquiry or receives informal records. |
| County / title follow-up | `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii/incoming/dot-gnrr-records-request-20260502/county-title-follow-up/` | Deeds, plats, title exceptions, maps, survey materials, and county/title follow-up results. |
| Sent request control | `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii/filings/outgoing/dot-gnrr-records-request-20260502/` | Outbound drafts and final sent-copy controls before responses are received. |
| Privileged response analysis | `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii/work-product/privileged/easement-validity-20260502/dot-gnrr-response-analysis/` | Operator/counsel analysis, send decisions, legal theory notes, and strategy. Do not mirror to repo without sanitization. |

## Pending Response Rows

These are placeholders only. They are not evidence entries until a produced record is saved, hashed, and registered.

| Request Lane | Target / Custodian | Records Expected | Current Status | Evidence Promotion Rule |
|---|---|---|---|---|
| GDOT open records | Georgia DOT Office of Legal Services / open records | July 17, 1998 lease/right-of-way records, MP386.3 crossing file, right-of-way maps, current control records, consent/no-objection records. | Ready to send after requester contact details and counsel/operator review. | Promote only after response files are saved in the GDOT intake path and SHA256 is recorded. |
| GNRR / Blue Ridge | GNRR / Blue Ridge Scenic Railway or verified successor/control entity | Crossing file, applications, approvals, amendments, assignments, fee/insurance/maintenance records, current operator/control records. | Counsel/operator send decision required. | Promote only after source identity and production path are confirmed; legal posture remains privileged until sanitized. |
| County / title | County real-estate records, closing/title file, survey/map lane | Deeds, plats, easements, railroad exceptions, title commitments, exception schedules, surveys, right-of-way maps. | Pull target open. | Promote only after record path, date pulled, and hash are recorded. |

## Response Metadata Template

Use one row per response file or discrete produced record.

| Field | Entry |
|---|---|
| Intake ID | `DOT-GNRR-YYYYMMDD-###` |
| Request lane | GDOT / GNRR-Blue-Ridge / County-title |
| Sender / custodian | TBD |
| Request sent date | TBD |
| Response received date | TBD |
| Production format | PDF / email / zip / image / link / no-records letter / fee estimate / other |
| Stored path | TBD |
| Bytes | TBD |
| SHA256 | TBD |
| Public or privileged | Public/source / privileged / mixed-needs-sanitization |
| Initial source classification | Lease / right-of-way map / crossing file / operator-control record / consent record / title record / no-records response / fee estimate / other |
| Workbench updates required | Source index / easement map / GNRR comparison / issue matrix / gap list / custody registry |
| Counsel verification required | Yes / no |

## Hash-And-Register Procedure

1. Save the original production exactly as received in the correct NAS intake lane.
2. If the response is an email with attachments, save the email body and every attachment separately.
3. Generate SHA256 for every saved file before extraction or annotation.
4. Add each file to the evidence custody registry only after the hash exists.
5. If the response contains mixed public and privileged material, keep the original in NAS intake and create a sanitized extract before repo use.
6. Update the DOT / railroad right-of-way source index before changing claim or issue matrices.

## Source Finding Conversion Rules

| Response Type | Allowed Repo-Safe Finding | Prohibited Shortcut |
|---|---|---|
| Full GDOT lease/right-of-way agreement | Identify parties, dates, covered corridor, assignment/successor terms, and termination/status language after page pinning. | Do not conclude private easement validity from the lease alone. |
| Right-of-way map / parcel map | Identify mapped corridor, crossing location, and relationship to Lots 14-16 after page or image pinning. | Do not infer title ownership beyond the record language/map. |
| Crossing file / consent record | Identify whether consent, notice, approval, objection, insurance, fee, or maintenance records exist. | Do not characterize motive or bad faith without counsel review. |
| Current operator/control record | Identify operator, lessee, assignee, or control party as of the relevant dates. | Do not assume authority to bind GDOT or GNRR unless the record says so. |
| No-records response | Record that the custodian reported no responsive records for the request as framed. | Do not treat no-records as proof that the records never existed. |

## Immediate Operator Action

1. Fill requester contact details in the DOT / GNRR records-request packet.
2. Send or counsel-review the GDOT request.
3. Decide whether the GNRR / Blue Ridge request should be informal, preserved for subpoena, or held for counsel.
4. Save any sent request and any response into the intake paths above.
5. Hash and register before analysis.
