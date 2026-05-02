# Easement Validity Source Map - 7IL Case II

Date: 2026-05-02
Classification: Repo-safe workbench based on public/court-record and curated source materials. Does not include privileged email substance.
Operator service status: Gary Knight has not been served as of 2026-05-02.

This is not a filing and not legal advice. It is a source-control map for testing 7IL's unauthorized-easement, slander-title, quiet-title, injunction, warranty-title, and fee theories.

## Control Rule

Do not treat the March 17, 2025 recorded easement as either valid or invalid by label. Test it through source gates:

1. chain of title and ownership for Lots 14, 15, 16, and the railroad/right-of-way crossing;
2. authority of Gary Knight and Thor A. James to amend or replace prior easement terms between their properties;
3. railroad/right-of-way license or crossing agreement limits;
4. whether the instrument affects property interests conveyed to 7IL at closing;
5. whether closing documents reserved, disclosed, waived, excepted, or objected to the easement;
6. whether any Georgia-law mutual-modification / recording theory is supportable after counsel review.

## Source Anchors

| Source | Path | SHA256 / Note | Current Use |
|---|---|---|---|
| Case II complaint | `curated/documents/01_operative_pleadings/Complaint_7IL_v_Knight_James_NDGA-II.pdf` | Curated complaint set | Counts II-V and VII attack the March 17, 2025 easement. |
| Exhibit I - March 17, 2025 recorded easement | `curated/documents/02_complaint_exhibits/Exhibit_I_Unauthorized_Easement_2025-03-17.pdf` | `43cccf435c5128dac2cf5139b308e01c057ed23c39433e6746626e7ebc306b64` | Operative recorded instrument challenged by 7IL. |
| 2021 Thor James easement | `curated/documents/case-i-context/04_deposition_exhibits_7il/Exh._B___2021.03.07_Thor_James_Easement.pdf` | `d0f1932aec2b26f8a36b389e18420aa0496b5d5d8b2ced848c6fd1c3d7a0d371` | Prior access/path easement between Knight and James; includes railroad-crossing language. |
| 2021 Thor James water easement | `curated/documents/case-i-context/04_deposition_exhibits_7il/Exh._C___2021.03.07_Thor_James_Water_Easement.pdf` | `0677afed54ddd35effac9b6ecd004541b6581bb457cc24d5fb649992f6b46a33` | Separate water easement / maintenance agreement. |
| 2021 easement email exhibit | `curated/documents/case-i-context/04_deposition_exhibits_7il/Exh._L___2021.05.31_Easement_Emails.pdf` | `d93b90bcd3a2864305b3755770e9e58d7eb094a69b1eec980cbef36fc97dd610` | Case I easement-email context and attachment references, including RR crossing agreement. |
| Case I Doc. 64-10 proposed easement | `/mnt/fortress_nas/Corporate_Legal/Business_Legal/# Pleadings - GAND/#64-10 Proposed Easement.pdf` | `c545462e58ae1e28178455ef59c1f9cd9a5b8ac0809170cab771c284e2be3914` | Case I proposed easement source. |
| Case I Doc. 64-13 proposed easement | `/mnt/fortress_nas/Corporate_Legal/Business_Legal/# Pleadings - GAND/#64-13 Proposed Easement.pdf` | `9e26e54c947859c9970cffebbbd0c3baf8bce8b1328d3296b868d6de01fcbf8b` | Case I proposed easement source; extraction sparse, manual PDF review needed. |
| Case I Doc. 78 MSJ order | `curated/documents/case-i-context/03_judgment_and_orders/78_Order_on_MSJs.pdf` | Curated Case I context | Finds River Heights amendment sufficiently definite and identifies Wilson drafting responsibility/factual disputes. |
| River Heights deed and closing package | `curated/documents/02_complaint_exhibits/Exhibit_J_Warranty_Deed_River_Heights_2025-06-02.pdf`; final closing package still missing | Deed hash recorded in closing-package inventory | Needed to test disclosure, exceptions, waiver, merger, title covenant, and objection posture. |

## Current Source Findings

| Issue | Source Finding | Classification |
|---|---|---|
| March 17 instrument | Exhibit I is the challenged recorded easement between Gary Knight and Thor A. James. Extracted text identifies Lots 14, 15, and 16 and includes a railroad-crossing-conditions section. | Source pinned; legal effect open. |
| Railroad crossing | Exhibit I states crossing use is subject to a Private Road Grade Crossing Agreement dated September 1, 2016 with Georgia Northeastern Railroad Company LLC. | Strong source lead; underlying crossing agreement must be pulled and title/authority verified. |
| Prior 2021 easement | The 2021 Thor James easement includes path/crossing language and states crossing use is subject to the Private Road Grade Crossing Agreement. | Source pinned; compare to 2025 replacement/modified terms. |
| DOT / railroad ownership theory | Operator theory is that prior easement drafting attempted to grant or burden a railroad crossing/right-of-way Knight did not own, while Knight had crossing-use rights by license/agreement. | Needs source proof: DOT/railroad title/right-of-way records, GNRR crossing agreement, and counsel review. |
| Mutual modification theory | Operator theory is that Knight and James, as parties to the easement relationship, could agree to changed terms and record a replacement or modified easement. | Legal theory only; Georgia-law verification required before filing use. |
| Impact on 7IL title | Plaintiff claims the 2025 easement clouds or burdens River Heights title. | Requires River Heights deed package, title commitment, exception schedule, and closing-file objection/reservation record. |
| Drafting / negotiation lane | Post-recording draft/negotiation materials exist in NAS-only privileged work product. | Do not reproduce privileged substance in repo. |

## Claim Mapping

| Case II Count | Easement Issue | Fortress Source Test | Missing Gate |
|---|---|---|---|
| Count II - slander of title | Whether the March 17 easement was false, unauthorized, malicious, and caused special damages. | Show source basis for Knight/James authority, prior easement chain, railroad-crossing agreement, and objective good-faith basis. | Georgia-law element review, special-damages proof, title/closing file. |
| Count III - declaratory relief | Whether the March 17 easement is void/unenforceable/no legal effect. | Compare 2021 easement, 2025 instrument, crossing agreement, and deed/title exceptions. | Legal authority map and full instrument chain. |
| Count IV - quiet title / quia timet | Whether the easement clouds River Heights title. | Test whether 7IL took title subject to any recorded exceptions, disclosures, reservations, or objections. | Final ALTA/title commitment/settlement statement. |
| Count V - injunctive relief | Whether removal/cancellation is warranted. | Require merits proof plus irreparable-harm facts. | Title harm and current-use evidence. |
| Count VII - warranty of title | Whether Knight breached deed covenants by executing/maintaining the easement. | Test deed language, exception schedule, timing, knowledge, and whether easement burdened conveyed property. | River Heights closing/title package. |
| Count VIII - attorney fees | Whether easement conduct supports bad faith/stubborn litigiousness. | Build good-faith source record and avoid unsupported legal conclusions. | Full correspondence, raw Wilson Pruitt export, counsel review. |

## Evidence Pull List

| Priority | Source Needed | Why |
|---:|---|---|
| P1 | Private Road Grade Crossing Agreement dated September 1, 2016 / GNRR-0184 Knight Crossing MP 386.3 | Controls railroad crossing rights and limits. |
| P1 | Georgia DOT / railroad right-of-way ownership records for the crossing area | Tests operator theory that Knight did not own the crossing/right-of-way itself. |
| P1 | Full River Heights title commitment, ALTA/settlement statement, exception schedule, closing instructions, and deed transmittals | Controls warranty/title, waiver, exception, objection, and closing conduct. |
| P1 | Complete 2021 and 2025 recorded easement instruments, book/page data, plats, and surveys | Builds instrument chain and scope comparison. |
| P1 | Privileged post-recording draft/negotiation lane, reviewed and sanitized by counsel/operator | Determines whether later draft conduct helps or hurts the good-faith/mitigation story. |
| P2 | Thor James communications and assent records | Supports or limits mutual-modification theory. |
| P2 | Current use/access evidence for Lots 14-16 and railroad crossing | Separates theoretical title cloud from practical access/use facts. |

## Immediate Work Orders

1. Pull and hash the September 1, 2016 crossing agreement and any DOT/railroad right-of-way records.
2. Build an instrument comparison: 2021 Thor James easement, 2025 recorded easement, and any later draft replacement terms.
3. Pull River Heights final title/closing package to test whether 7IL objected, accepted, excepted, waived, or reserved rights.
4. Ask counsel to verify Georgia mutual-modification/recording authority before using that theory in a filing.
5. Keep counsel/advice communications and draft negotiation strategy NAS-only until sanitized.
