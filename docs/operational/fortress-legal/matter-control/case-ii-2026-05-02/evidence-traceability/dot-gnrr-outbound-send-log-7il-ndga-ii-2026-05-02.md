# DOT / GNRR Outbound Send Log - 7IL Case II

Date: 2026-05-02
Classification: Repo-safe send-control log. Does not include private requester contact details, privileged email substance, or legal strategy.
Operator service status: Gary Knight has not been served as of 2026-05-02.

This is not a filing and not legal advice. This log tracks outbound request drafts created from the DOT / GNRR records-request packet. No request is treated as sent until the operator records an actual sent date and stores the sent copy in NAS intake.

## Outbound Drafts

| Draft | NAS Path | Intended Recipient / Lane | Status | Before Send |
|---|---|---|---|---|
| GDOT Open Records Request | `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii/filings/outgoing/dot-gnrr-records-request-20260502/GDOT_Open_Records_Request_OUTBOUND_DRAFT_7IL_NDGA_II_20260502.md` | GDOT Office of Legal Services / `openrecords@dot.ga.gov` | Draft staged; not sent by Codex. | Add requester contact details; operator/counsel review; decide whether to attach or reference GNRR extract. |
| GNRR / Blue Ridge Records Inquiry | `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii/filings/outgoing/dot-gnrr-records-request-20260502/GNRR_Blue_Ridge_Records_Inquiry_COUNSEL_REVIEW_DRAFT_7IL_NDGA_II_20260502.md` | GNRR / Blue Ridge / verified successor-control lane | Counsel-review draft staged; not sent by Codex. | Verify corporate/operator identity; counsel decides informal inquiry, preservation letter, subpoena target, or hold. |

## Send Recording Template

Use one row per outbound transmission after it is actually sent.

| Field | Entry |
|---|---|
| Outbound ID | `DOT-GNRR-SENT-YYYYMMDD-###` |
| Request lane | GDOT / GNRR-Blue-Ridge / County-title |
| Sent date/time | TBD |
| Sent by | TBD |
| Sent from | TBD |
| Sent to | TBD |
| Subject | TBD |
| Attachments included | None / GNRR extract / other |
| Stored sent-copy path | TBD |
| SHA256 of sent copy | TBD |
| Response intake path | TBD |
| Follow-up date | TBD |

## Send Rules

1. Do not send from repo text directly; send from the NAS outbound draft after requester contact details are added.
2. Save the sent email or final PDF exactly as sent into the DOT / GNRR intake folder.
3. Hash the sent copy before logging it as a sent-control record.
4. Keep legal strategy, rationale, or counsel communications in the privileged analysis folder.
5. If the request is revised before sending, save the revised final version separately and hash it.

## Current Status

| Lane | Current Status | Next Action |
|---|---|---|
| GDOT open records | Draft staged; not sent by Codex. | Operator fills contact details and sends or asks counsel to review. |
| GNRR / Blue Ridge | Counsel-review draft staged; not sent by Codex. | Counsel/operator decides whether and how to send. |
| County / title | No outbound draft in this pass. | Pull from title/county records lane after closing package and survey priorities are set. |
