# Case I-to-Case II Overlap Chart - 7IL Case II

Date: 2026-05-02
Classification: Repo-safe workbench based on public/court-record sources. Does not include privileged email substance.
Operator service status: Gary Knight has not been served as of 2026-05-02.

This is not a filing and not legal advice. It is a control chart for testing claim preclusion, issue preclusion, judgment-boundary, and abuse-of-process theories without overclaiming what the Case I record actually decided.

## Control Rule

Do not argue "overlap" as a conclusion. For each Case II theory, identify:

1. the Case I issue or order it touches;
2. whether Case I actually decided that issue;
3. whether Case II alleges a new post-judgment or post-closing act;
4. what source is still missing; and
5. whether the item belongs in an answer defense, Rule 12 screen, discovery request, or counsel-only counterclaim review.

## Source Anchors

| Source | Path | SHA256 / Note | Current Use |
|---|---|---|---|
| Case II complaint | `curated/documents/01_operative_pleadings/Complaint_7IL_v_Knight_James_NDGA-II.pdf` | Curated complaint exhibit set | Counts I-VIII and plaintiff's post-judgment/new-act framing. |
| Case I Doc. 49 contempt motion | `/mnt/fortress_nas/Corporate_Legal/Business_Legal/# Pleadings - GAND/#49 Motion for Contempt.pdf` | `644a51fbd5ee56ec0ac3dd3843f055094ceba8d0394c1a357d438452beadff11` | Discovery/compliance dispute over phone recovery and production; source for prior contempt posture. |
| Case I Doc. 51 response to contempt motion | `/mnt/fortress_nas/Corporate_Legal/Business_Legal/# Pleadings - GAND/#51 RIOT Mtn. for Contempt.pdf` | `6b486677c9bb6b25e8968c92462528ed0647166c5dcd580cd647573f2b98586f` | 7IL response accusing Knight of delay/bad faith; useful for pattern/timing review, not merits adjudication. |
| Case I Doc. 54 contempt order | `/mnt/fortress_nas/Corporate_Legal/Business_Legal/# Pleadings - GAND/#54 Order Denying Motion for Contempt.pdf` | `d3895fa9f8eae4a16307175072c63daacf52eb1f90cd8ec91ee177610646e116` | Denied Doc. 49 without prejudice for failure to follow standing-order procedure; not a merits ruling on contempt facts. |
| Case I Doc. 78 MSJ order | `curated/documents/case-i-context/03_judgment_and_orders/78_Order_on_MSJs.pdf` | Curated Case I context | Defines River Heights easement amendment, Fish Trap amendment, encroachment, closing, breach, and specific-performance issues at summary judgment. |
| Case I Doc. 90 order on reconsideration | `/mnt/fortress_nas/Corporate_Legal/Business_Legal/# Pleadings - GAND/#90 Order on MFR.pdf` | `3a2e71f8d640a8ac947f72a731378d9e23f0e0c31492216edd023779a69f9103` | Doc. 134 references this for Fish Trap enforceability/specific performance; extracted text is partial and needs manual review/OCR if used heavily. |
| Case I Doc. 96 Fish Trap closing order | `/mnt/fortress_nas/Corporate_Legal/Business_Legal/# Pleadings - GAND/#96 Order to Close 92 Fish Trap.pdf` | `b6f2579b4c51f2a5cd1cf4ff5cb4b375a55beac92c680d25a9a80b2425878129` | Allows good-faith Fish Trap closing work, financing, inspection, title update, escrow negotiation, and appeal waiver; acknowledges damages reservation. |
| Case I Doc. 100 limited waiver | `curated/documents/case-i-context/#100 Limited Waiver of Appeal Rights.pdf` | Public court record / curated copy | Fish Trap specific-performance appeal waiver; preserves damages/other issues in extracted text. |
| Case I Doc. 134 specific-performance order | `curated/documents/02_complaint_exhibits/Exhibit_A_Case-I_Doc134_Specific_Performance_Order.pdf` | `405e6b9341490e85bd0958af1eed083d23cf01b1c3b33159fcadfca1c8cf647e` | Jury verdict, damages/fees, Fish Trap enforceability reference, and closing command. |
| Case I Doc. 135 final judgment | `curated/documents/02_complaint_exhibits/Exhibit_B_Case-I_Doc135_Final_Judgment.pdf` | `bac265349f80f6b74c9cc45c7cc856b59ef4c39ee8e98a37b93c8bb226740b87` | Final money judgment plus closing command. |

## Case I Boundary Findings

| Boundary | Current Finding | Do Not Overclaim |
|---|---|---|
| Contempt motion | Doc. 54 denied Doc. 49 without prejudice for failure to comply with the Court's standing-order discovery-dispute procedure. | Do not treat the denial as a merits finding that 7IL complied or that Knight's discovery concerns lacked substance. |
| Fish Trap closing order | Doc. 96 allowed good-faith closing work, inspection, title update, escrow negotiation, and specific-performance appeal waiver while acknowledging Knight's damages reservation. | Do not treat Doc. 96 as an itemized repair-survival order or as a waiver of all Fish Trap damages defenses. |
| Final judgment | Doc. 134/135 ordered money judgment and closing within not less than 105 days. Extracted text does not itemize repair survival, new inspections, easement cancellation, or post-closing repair remedies. | Do not argue the judgment extinguished everything without closing-package and survival/waiver analysis. |
| Doc. 78 easement findings | Doc. 78 found River Heights amendment sufficiently definite, Fish Trap amendment too vague in part, and left factual disputes on performance/readiness and what happened at closing. | Do not treat all easement issues as fully decided; separate decided amendment validity from later 2025 recorded-instrument issues. |
| Doc. 90 source | Doc. 134 says Doc. 90 ruled Fish Trap PSA enforceable and specific performance available. | Extracted Doc. 90 text is incomplete/partial; use with manual PDF review before final reliance. |

## Claim / Issue Overlap Matrix

| Case II Issue | Complaint Theory | Case I Touchpoint | Overlap Classification | Defense / Response Use | Missing Source Gate |
|---|---|---|---|---|---|
| Count I - post-judgment repairs | Repairs survived judgment and closing; 2025 inspections show unrepaired or worsened conditions. | Case I PSAs/amendments, 2021 inspections, Doc. 134/135 closing command, Doc. 96 Fish Trap inspection/title/escrow language. | Mixed: same contract universe, but plaintiff frames new post-judgment/post-closing breach. | Deny global survival conclusions; require item-by-item written obligation, completion proof, closing reservation/waiver, same-condition proof, and damages. | Closing package, final ALTA/settlement/escrow file, completion proof, any distinct 2025 River Heights report. |
| River Heights repair theory | Plaintiff ties 2021/2025 inspection material to seller repair obligations. | River Heights Amendment #2 and Case I / 2021 inspection source; Terry Wilson production pins repair-reference pages. | High source overlap with Case I evidence; post-closing survival remains unproven. | Use existing River Heights line matrix; force 31-item filter and survival/waiver gates. | Completion proof and closing-package reservation/waiver records. |
| Fish Trap repair theory | Plaintiff ties 2021/2025 inspection material to Amendment #3 and alleged continued obligations. | Fish Trap Amendment #3; Doc. 96 allowed Fish Trap inspection/title activity and preserved damages dispute posture. | High source overlap plus later inspection evidence; exact same-condition proof open. | Use Fish Trap overlap matrix; classify each 2025 item as same item, adjacent item, new condition, or maintenance recurrence. | Completion proof, closing package, source-authenticated 2025 Fish Trap report/attachments. |
| Counts II-V - unauthorized River Heights easement | March 2025 recorded easement allegedly burdens River Heights and supports slander, declaration, quiet title, and injunction. | Doc. 78 River Heights amendment/easement findings; Wilson drafting responsibility; 2021 easement discussions. | New recorded-instrument act with strong Case I easement-background overlap. | Preserve defenses that Case II repackages the easement dispute while also preparing merits map for validity/authority/recording. | Easement instrument chain, right-of-way/railroad authority, closing/title file, drafting record. |
| Count VI - Fish Trap ejectment / driveway | Plaintiff alleges no valid easement/license/boundary adjustment and seeks removal/restoration. | Doc. 78 Fish Trap encroachment/proposed land swap/survey discussion; 2021 closing failure record. | Strong factual overlap with Case I encroachment record; remedy framed as current possession/ejectment. | Preserve preclusion/estoppel defenses only after survey/source review; build physical-evidence map. | Survey, photos, title/closing docs, deed exceptions, post-closing access/use record. |
| Count VII - breach of warranty of title | Warranty deed allegedly breached because Knight recorded/maintained unauthorized easement. | Doc. 78 dismissed earlier breach-of-warranty title claim per Doc. 90 background; 2025 deed is a later closing instrument. | Same title/easement theme but potentially new deed-covenant event. | Do not rely on dismissal alone; test deed language, exceptions, knowledge, and timing. | River Heights deed package, title commitment, settlement statement, exception schedule, closing attorney file. |
| Count VIII - attorney fees | Bad faith/stubborn litigiousness tied to alleged repair breaches and easement/title conduct. | Case I fee award; contempt dispute accusations; closing/judgment history. | Overlapping conduct narrative, but fee theory depends on Case II merits and bad-faith proof. | Deny fee entitlement; build good-faith record and source chronology. | Full correspondence, service status, closing package, raw Wilson Pruitt export. |
| Potential abuse-of-process counterclaim | Operator theory: Case II may weaponize post-judgment process after overlapping Case I/conflict/closing issues. | Doc. 49/51/54 contempt dispute; Doc. 78/96/134/135; Case II complaint timing and scope. | High strategic value but high pleading risk. | Counsel-only review; do not plead without element memo and source support. | Case I docket chronology, post-judgment correspondence, service proof, raw emails, damages/ulterior-purpose evidence. |
| Claim preclusion / issue preclusion | Plaintiff pleads post-judgment/new acts to avoid preclusion. | Case I judgment/orders and claims actually decided. | Requires issue-by-issue analysis; not automatic. | Preserve in answer/defenses where supported; use chart to target discovery. | Full Case I verdict form, jury instructions, pretrial order, Doc. 90 complete review, appeal/waiver record. |

## Litigation-Control Buckets

| Bucket | Items | Control Treatment |
|---|---|---|
| Already decided / source anchored | Doc. 134/135 money judgment and closing command; Doc. 54 procedural denial without prejudice; Doc. 78 summary-judgment boundaries. | Use as hard boundaries, not narrative shortcuts. |
| Overlapping but not fully decided | Repair survival, easement performance/readiness, Fish Trap encroachment, title/warranty themes. | Preserve defenses and demand itemized sources. |
| Allegedly new acts | March 2025 easement recording, 2025 inspections, June 2025 closings/deeds, post-closing demands. | Build independent source proof and test whether new act is actually new or repackaged. |
| Counsel-only offensive review | Abuse of process, Thatcher individual capacity, Wilson role, punitive theory. | Keep out of filings until element/source memo is complete. |

## Immediate Work Orders

1. Add the full Case I verdict form, jury instructions, and pretrial order to this overlap chart.
2. Manually review or OCR Doc. 90 because the extracted text is incomplete while Doc. 134 relies on it.
3. Tie the overlap chart to the closing-package inventory once Wilson Pruitt/raw closing materials land.
4. Build the easement validity source map next: recorded instrument, drafting authority, railroad/right-of-way basis, title exceptions, and closing conduct.
5. Build the Fish Trap survey/driveway physical-evidence map after the easement source map.

## Counsel Package Warning

This chart supports issue spotting and source control. It should not be presented as a final preclusion or counterclaim memo until counsel reviews the actual elements, procedural posture, and complete Case I record.
