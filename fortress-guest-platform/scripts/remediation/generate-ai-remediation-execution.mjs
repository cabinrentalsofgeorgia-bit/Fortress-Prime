import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { join } from "node:path";

const root = process.cwd().endsWith("fortress-guest-platform")
  ? process.cwd()
  : join(process.cwd(), "fortress-guest-platform");
const outDir = join(root, "operational-memory", "remediation");
const packetDir = join(outDir, "disposition-packets");

const manifests = {
  sourceIntegrity: "/mnt/fortress_nas/audits/fortress-source-integrity-20260506-090537.json",
  sourceRemediation: "/mnt/fortress_nas/audits/fortress-source-remediation-20260506-092630.json",
  sourceLinkRepair: "/mnt/fortress_nas/audits/fortress-source-link-repair-20260506-095253.json",
  targetedSourceCompletion: "/mnt/fortress_nas/audits/fortress-targeted-source-completion-20260506-151821.json",
  limitedSignoffCandidate: "/mnt/fortress_nas/audits/fortress-limited-signoff-candidate-20260506-153336.json",
  signoffPacket: "/mnt/fortress_nas/audits/fortress-signoff-packet-20260506-084028.json",
};

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function sha256(value) {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

function groupBy(items, keyFn) {
  return items.reduce((acc, item) => {
    const key = keyFn(item) ?? "unknown";
    acc[key] ??= [];
    acc[key].push(item);
    return acc;
  }, {});
}

function severityFor(item) {
  if (item.materiality_tier === "tier_1_high_materiality") return "high";
  if (item.item_type === "contradiction_candidate") return "high";
  if (item.materiality_tier === "tier_2_supporting_packet_gap") return "medium";
  return "low";
}

function primaryCategory(item) {
  if (item.locked_restricted_involved || item.blocker_type === "locked_or_privilege_limited") {
    return "restricted_metadata_only";
  }
  if (item.item_type === "contradiction_candidate") return "contradiction_candidate";
  if (item.item_type === "entity_dossier") return "ambiguous_entity_mapping";
  if (item.item_type === "evidence_binder") return "incomplete_source_chain";
  if (item.item_type === "issue_matrix" || item.item_type === "theory_packet") return "unsupported_assertion";
  return "missing_source";
}

function secondaryCategories(item) {
  const categories = ["excluded_from_reliance", "human_review_required"];
  if (item.counsel_review_required) categories.push("counsel_review_required");
  if (item.source_status === "unsupported") categories.push("missing_source", "low_confidence_source");
  if (item.item_type === "contradiction_candidate") categories.push("contradiction_candidate");
  if (item.locked_restricted_involved) categories.push("restricted_metadata_only");
  return [...new Set(categories)];
}

function automationSafety(item) {
  if (item.locked_restricted_involved) return "metadata_only_route_to_counsel_no_agent_content_access";
  if (item.item_type === "contradiction_candidate") return "packet_generation_only_human_contradiction_review_required";
  return "recommendation_only_no_source_promotion";
}

function packetTypeFor(category) {
  if (category === "restricted_metadata_only") return "restricted-metadata-only-packet";
  if (category === "contradiction_candidate") return "contradiction-review-packet";
  if (category === "incomplete_source_chain") return "evidence-chain-packet";
  if (category === "ambiguous_entity_mapping") return "missing-source-packet";
  if (category === "unsupported_assertion") return "missing-source-packet";
  return "missing-source-packet";
}

function writeJson(path, payload) {
  writeFileSync(path, `${JSON.stringify(payload, null, 2)}\n`);
}

mkdirSync(packetDir, { recursive: true });

const limited = readJson(manifests.limitedSignoffCandidate);
const targeted = readJson(manifests.targetedSourceCompletion);
const sourceLinkRepair = readJson(manifests.sourceLinkRepair);
const unresolved = limited.unresolved_blocker_register_v2 ?? [];
const targetedByItem = new Map((targeted.refined_unresolved_register ?? []).map((item) => [item.item_id, item]));
const linkRepairByItem = new Map((sourceLinkRepair.refined_unresolved_register ?? []).map((item) => [item.item_id, item]));

const standingLabels = {
  counselStatus: "COUNSEL_SIGNOFF_PENDING",
  externalSubmissionAuthority: "NOT_AUTHORIZED",
  finalLegalConclusions: "NOT_CREATED",
  legalAdviceStatus: "NOT FINAL LEGAL ADVICE",
  schemaRlsPolicyMutation: "NOT_PERFORMED",
};

const governanceBoundaries = [
  "no_source_promotion",
  "no_signoff",
  "no_final_legal_advice",
  "no_external_authority",
  "metadata_only_restricted_handling",
  "human_review_required",
];

const prohibitedActions = [
  "source_promotion",
  "mark_resolved",
  "counsel_signoff",
  "final_legal_conclusion",
  "external_submission",
  "restricted_content_inspection",
  "schema_rls_policy_mutation",
];

const classifications = unresolved.map((item, index) => {
  const targetedRecord = targetedByItem.get(item.item_id);
  const linkRepairRecord = linkRepairByItem.get(item.item_id);
  const category = primaryCategory(item);
  return {
    issueId: item.item_id,
    sourceRecordId: item.source_record_id ?? targetedRecord?.targeted_source_completion_id ?? null,
    category,
    secondaryCategories: secondaryCategories(item),
    itemType: item.item_type,
    severity: severityFor(item),
    materialityTier: item.materiality_tier,
    automationSafety: automationSafety(item),
    humanReviewRequired: true,
    counselReviewRequired: item.counsel_review_required !== false,
    evidenceRefs: [
      "fortress-guest-platform/docs/operational/ai-remediation-source-inventory-2026-05-06.md",
      manifests.targetedSourceCompletion,
      manifests.limitedSignoffCandidate,
    ],
    sourceRefs: [],
    restrictedBoundary: Boolean(item.locked_restricted_involved),
    recommendedNextAction: item.locked_restricted_involved
      ? "Route metadata-only item for counsel-controlled review; do not inspect locked content."
      : item.required_next_action ?? "Prepare reviewer packet and keep excluded from reliance.",
    prohibitedActions,
    confidence: Number(item.confidence ?? (category === "restricted_metadata_only" ? 0.75 : 0.62)),
    signoffImpact: item.signoff_impact ?? "blocks_full_packet_signoff",
    sourceStatus: item.source_status ?? targetedRecord?.final_state ?? "unsupported",
    candidateOutcome: item.candidate_outcome ?? "exclude_unsupported",
    track: targetedRecord?.track ?? null,
    linkRepairOutcome: linkRepairRecord?.repair_outcome ?? null,
    sourcePromotionAllowed: false,
    legalConclusion: false,
    signoffAuthority: false,
    ordinal: index + 1,
  };
});

const categoryGroups = groupBy(classifications, (item) => item.category);
const itemTypeGroups = groupBy(classifications, (item) => item.itemType);
const tierGroups = groupBy(classifications, (item) => item.materialityTier);

const classificationPayload = {
  schemaVersion: "1.0.0",
  generatedAt: new Date().toISOString(),
  sourceRefs: Object.values(manifests),
  standingLabels,
  governanceBoundaries,
  validationStatus: { status: "AI_TRIAGE_METADATA_ONLY_REVIEW_REQUIRED" },
  rollbackRefs: ["git_revert_ai_remediation_execution_commits"],
  noSecrets: true,
  noConfidentialText: true,
  sourcePromotionAllowed: false,
  legalConclusion: false,
  signoffAuthority: false,
  unresolvedIssueCount: classifications.length,
  summary: {
    byCategory: Object.entries(categoryGroups).map(([category, items]) => ({ category, count: items.length })),
    byItemType: Object.entries(itemTypeGroups).map(([itemType, items]) => ({ itemType, count: items.length })),
    byMaterialityTier: Object.entries(tierGroups).map(([materialityTier, items]) => ({ materialityTier, count: items.length })),
    counselReviewRequired: classifications.filter((item) => item.counselReviewRequired).length,
    restrictedMetadataOnly: classifications.filter((item) => item.restrictedBoundary).length,
  },
  issues: classifications,
};

const clusters = [
  ...Object.entries(categoryGroups).map(([category, items]) => ({
    clusterId: `cluster-category-${category}`,
    issueIds: items.map((item) => item.issueId),
    clusterType: category,
    sharedRootCause: category === "restricted_metadata_only" ? "restricted_or_privilege_limited_metadata_only" : "unresolved_source_support_gap",
    recommendedBatchAction: category === "restricted_metadata_only"
      ? "Route to counsel-only metadata review; preserve locked-content boundary."
      : "Generate reviewer disposition packet and request source attachment, narrowing, or continued exclusion.",
    automationSafety: items.some((item) => item.restrictedBoundary) ? "metadata_only_no_agent_content_access" : "recommendation_only",
    humanReviewRequired: true,
    evidenceRefs: [manifests.limitedSignoffCandidate],
  })),
  ...Object.entries(itemTypeGroups).map(([itemType, items]) => ({
    clusterId: `cluster-item-type-${itemType}`,
    issueIds: items.map((item) => item.issueId),
    clusterType: `item_type_${itemType}`,
    sharedRootCause: "same_review_surface_or_work_product_type",
    recommendedBatchAction: "Batch reviewer packet review by item type.",
    automationSafety: "queue_grouping_only_no_resolution",
    humanReviewRequired: true,
    evidenceRefs: [manifests.limitedSignoffCandidate],
  })),
  ...Object.entries(tierGroups).map(([tier, items]) => ({
    clusterId: `cluster-tier-${tier}`,
    issueIds: items.map((item) => item.issueId),
    clusterType: `materiality_${tier}`,
    sharedRootCause: "same_materiality_priority_tier",
    recommendedBatchAction: "Prioritize review by materiality tier without changing source status.",
    automationSafety: "priority_routing_only",
    humanReviewRequired: true,
    evidenceRefs: [manifests.limitedSignoffCandidate],
  })),
];

const clusterPayload = {
  schemaVersion: "1.0.0",
  generatedAt: new Date().toISOString(),
  sourceRefs: [manifests.limitedSignoffCandidate],
  standingLabels,
  governanceBoundaries,
  validationStatus: { status: "CLUSTERED_FOR_REVIEW_ONLY" },
  rollbackRefs: ["git_revert_ai_remediation_execution_commits"],
  noSecrets: true,
  noConfidentialText: true,
  clusters,
};

const candidateSpecs = [
  {
    type: "source-link repair proposal",
    predicate: (item) => !item.restrictedBoundary && ["missing_source", "unsupported_assertion", "incomplete_source_chain"].includes(item.category),
    action: "Prepare candidate source-link repair request for reviewer source attachment or narrowing.",
    requiredValidation: ["reviewer_confirms_source_metadata", "no_document_body_text_in_packet"],
  },
  {
    type: "duplicate closure recommendation",
    predicate: (item) => !item.restrictedBoundary && itemTypeGroups[item.itemType]?.length > 1,
    action: "Recommend duplicate or batch review where item IDs share item type and source status.",
    requiredValidation: ["human_duplicate_review", "no_status_mutation"],
  },
  {
    type: "contradiction packet generation",
    predicate: (item) => item.category === "contradiction_candidate",
    action: "Generate contradiction review packet for human review; do not resolve contradiction.",
    requiredValidation: ["human_contradiction_review", "no_legal_finding"],
  },
  {
    type: "restricted metadata-only routing",
    predicate: (item) => item.restrictedBoundary,
    action: "Route metadata-only item to counsel-controlled review without content inspection.",
    requiredValidation: ["restricted_boundary_acknowledgment", "no_agent_content_access"],
  },
];

const safeCandidates = candidateSpecs.map((spec, index) => {
  const issues = classifications.filter(spec.predicate);
  return {
    candidateId: `candidate-${String(index + 1).padStart(2, "0")}-${spec.type.replaceAll(" ", "-")}`,
    issueIds: issues.map((item) => item.issueId),
    candidateType: spec.type,
    proposedAction: spec.action,
    automationSafety: "prepare_recommendation_only",
    requiredValidation: spec.requiredValidation,
    requiredHumanApproval: true,
    rollbackPlan: "delete_or_revert_generated_packet; no source status mutation performed",
    evidenceRefs: [manifests.limitedSignoffCandidate],
    forbiddenActions: prohibitedActions,
    sourcePromotionAllowed: false,
    legalConclusion: false,
    signoffAuthority: false,
  };
});

const safeCandidatePayload = {
  schemaVersion: "1.0.0",
  generatedAt: new Date().toISOString(),
  sourceRefs: [manifests.limitedSignoffCandidate],
  standingLabels,
  governanceBoundaries,
  validationStatus: { status: "SAFE_CANDIDATES_PREPARED_FOR_REVIEW_ONLY" },
  rollbackRefs: ["git_revert_ai_remediation_execution_commits"],
  noSecrets: true,
  noConfidentialText: true,
  candidates: safeCandidates,
};

const packetGroups = groupBy(classifications, (item) => packetTypeFor(item.category));
const packets = Object.entries(packetGroups).map(([packetType, items], index) => ({
  packetId: `${packetType}-${String(index + 1).padStart(2, "0")}`,
  packetType,
  issueIds: items.map((item) => item.issueId),
  category: [...new Set(items.map((item) => item.category))].join("+"),
  summary: `${items.length} metadata-only unresolved items prepared for ${packetType} reviewer disposition.`,
  evidenceRefs: [manifests.limitedSignoffCandidate, "fortress-guest-platform/operational-memory/remediation/ai-remediation-classification.json"],
  recommendedDisposition: "review_required_continue_exclusion_until_approved",
  requiredReviewerAction: "Confirm source attachment, narrowing, duplicate disposition, counsel routing, or continued exclusion.",
  prohibitedActions,
  confidence: Number((items.reduce((sum, item) => sum + item.confidence, 0) / Math.max(items.length, 1)).toFixed(2)),
  humanReviewRequired: true,
  counselReviewRequired: items.some((item) => item.counselReviewRequired),
  sourcePromotionAllowed: false,
  legalConclusion: false,
  signoffAuthority: false,
  noSecrets: true,
  noConfidentialText: true,
}));

for (const packet of packets) {
  writeJson(join(packetDir, `${packet.packetId}.json`), {
    schemaVersion: "1.0.0",
    generatedAt: new Date().toISOString(),
    standingLabels,
    governanceBoundaries,
    rollbackRefs: ["git_revert_ai_remediation_execution_commits"],
    ...packet,
    packetHash: sha256(packet),
  });
}

const packetIndex = {
  schemaVersion: "1.0.0",
  generatedAt: new Date().toISOString(),
  sourceRefs: [manifests.limitedSignoffCandidate],
  standingLabels,
  governanceBoundaries,
  validationStatus: { status: "DISPOSITION_PACKETS_GENERATED_FOR_REVIEW_ONLY" },
  rollbackRefs: ["git_revert_ai_remediation_execution_commits"],
  noSecrets: true,
  noConfidentialText: true,
  packets: packets.map((packet) => ({
    packetId: packet.packetId,
    packetType: packet.packetType,
    issueCount: packet.issueIds.length,
    packetPath: `fortress-guest-platform/operational-memory/remediation/disposition-packets/${packet.packetId}.json`,
    humanReviewRequired: packet.humanReviewRequired,
    counselReviewRequired: packet.counselReviewRequired,
    sourcePromotionAllowed: false,
  })),
};

const queueSpecs = [
  ["automation_prepared_human_review", (packet) => packet.packetType !== "restricted-metadata-only-packet", "source_reviewer"],
  ["counsel_review_required", (packet) => packet.counselReviewRequired, "counsel"],
  ["contradiction_review_required", (packet) => packet.packetType === "contradiction-review-packet", "counsel_or_senior_reviewer"],
  ["restricted_metadata_only", (packet) => packet.packetType === "restricted-metadata-only-packet", "counsel"],
  ["low_confidence_review", (packet) => packet.confidence < 0.7, "source_reviewer"],
  ["duplicate_review", () => true, "source_reviewer"],
  ["source_link_review", (packet) => packet.packetType === "missing-source-packet", "source_reviewer"],
  ["evidence_chain_review", (packet) => packet.packetType === "evidence-chain-packet", "source_reviewer"],
];

const queues = queueSpecs.map(([queueId, predicate, role]) => {
  const queuePackets = packets.filter(predicate);
  return {
    queueId,
    itemCount: queuePackets.reduce((sum, packet) => sum + packet.issueIds.length, 0),
    packetRefs: queuePackets.map((packet) => packet.packetId),
    priority: queueId === "counsel_review_required" || queueId === "contradiction_review_required" ? "high" : "normal",
    reviewRole: role,
    expectedAction: "review_packet_and_record_human_disposition_without_source_promotion",
    prohibitedAction: prohibitedActions,
    evidenceRefs: queuePackets.flatMap((packet) => packet.evidenceRefs),
    humanReviewRequired: true,
    sourcePromotionAllowed: false,
  };
});

const queuePayload = {
  schemaVersion: "1.0.0",
  generatedAt: new Date().toISOString(),
  sourceRefs: [manifests.limitedSignoffCandidate],
  standingLabels,
  governanceBoundaries,
  validationStatus: { status: "REVIEW_QUEUES_GENERATED_FOR_HUMAN_DISPOSITION" },
  rollbackRefs: ["git_revert_ai_remediation_execution_commits"],
  noSecrets: true,
  noConfidentialText: true,
  queues,
};

writeJson(join(outDir, "ai-remediation-classification.json"), classificationPayload);
writeJson(join(outDir, "remediation-clusters.json"), clusterPayload);
writeJson(join(outDir, "safe-automation-candidates.json"), safeCandidatePayload);
writeJson(join(outDir, "disposition-packet-index.json"), packetIndex);
writeJson(join(outDir, "reviewer-work-queues.json"), queuePayload);

const result = {
  ok: true,
  unresolvedIssueCount: classifications.length,
  classificationPath: "operational-memory/remediation/ai-remediation-classification.json",
  clusterCount: clusters.length,
  candidateCount: safeCandidates.length,
  packetCount: packets.length,
  queueCount: queues.length,
  noSecrets: true,
  noConfidentialText: true,
  sourcePromotionAllowed: false,
  legalConclusion: false,
  signoffAuthority: false,
};

console.log(JSON.stringify(result, null, 2));
