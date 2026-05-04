import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { HedgeFundSignalsShell } from "@/app/(dashboard)/financial/hedge-fund/_components/hedge-fund-signals-shell";

const latestSignals = [
  {
    ticker: "AA",
    bar_date: "2026-04-24",
    parameter_set_id: "11111111-1111-1111-1111-111111111111",
    parameter_set_name: "dochia_v0_estimated",
    dochia_version: "v0",
    monthly_state: 1,
    weekly_state: 1,
    daily_state: 1,
    momentum_state: 0,
    composite_score: 80,
    computed_at: "2026-05-02T12:00:00Z",
    monthly_channel_high: "75.6999",
    monthly_channel_low: "55.0400",
    weekly_channel_high: "75.6999",
    weekly_channel_low: "63.0300",
    daily_channel_high: "69.3750",
    daily_channel_low: "65.1500",
    state_labels: {
      monthly: "green",
      weekly: "green",
      daily: "green",
      momentum: "neutral",
    },
  },
  {
    ticker: "AGIO",
    bar_date: "2026-04-24",
    parameter_set_id: "11111111-1111-1111-1111-111111111111",
    parameter_set_name: "dochia_v0_estimated",
    dochia_version: "v0",
    monthly_state: -1,
    weekly_state: -1,
    daily_state: -1,
    momentum_state: 0,
    composite_score: -80,
    computed_at: "2026-05-02T12:00:00Z",
    monthly_channel_high: "36.3500",
    monthly_channel_low: "25.6200",
    weekly_channel_high: "35.9900",
    weekly_channel_low: "25.6200",
    daily_channel_high: "27.0350",
    daily_channel_low: "25.6200",
    state_labels: {
      monthly: "red",
      weekly: "red",
      daily: "red",
      momentum: "neutral",
    },
  },
];

const transitions = [
  {
    id: "22222222-2222-2222-2222-222222222222",
    ticker: "AA",
    parameter_set_name: "dochia_v0_estimated",
    transition_type: "breakout_bullish",
    from_score: 50,
    to_score: 80,
    from_bar_date: "2026-04-14",
    to_bar_date: "2026-04-22",
    from_states: { monthly: 1, weekly: 1, daily: -1, momentum: 0 },
    to_states: { monthly: 1, weekly: 1, daily: 1, momentum: 0 },
    detected_at: "2026-05-02T12:01:00Z",
    acknowledged_by_user_id: null,
    acknowledged_at: null,
    notes: "daily triangle green",
  },
];

const chartData = {
  ticker: "AA",
  sessions: 2,
  bars: [
    {
      ticker: "AA",
      bar_date: "2026-04-23",
      open: "66.00",
      high: "69.00",
      low: "65.00",
      close: "68.00",
      volume: 1000,
      daily_channel_high: "67.00",
      daily_channel_low: "64.00",
      weekly_channel_high: "70.00",
      weekly_channel_low: "60.00",
      monthly_channel_high: "75.00",
      monthly_channel_low: "55.00",
    },
    {
      ticker: "AA",
      bar_date: "2026-04-24",
      open: "68.00",
      high: "70.00",
      low: "66.00",
      close: "69.00",
      volume: 1200,
      daily_channel_high: "69.00",
      daily_channel_low: "65.00",
      weekly_channel_high: "70.00",
      weekly_channel_low: "61.00",
      monthly_channel_high: "75.00",
      monthly_channel_low: "55.00",
    },
  ],
  events: [
    {
      ticker: "AA",
      timeframe: "daily",
      state: "green",
      bar_date: "2026-04-24",
      trigger_price: "69.00",
      channel_high: "68.50",
      channel_low: "65.00",
      lookback_sessions: 3,
      reason: "close broke above channel",
    },
  ],
};

const whipsawRisk = {
  ticker: "AA",
  parameter_set_name: "dochia_v0_estimated",
  daily_trigger_mode: "close",
  sessions: 260,
  as_of: "2026-04-24",
  whipsaw_window_sessions: 5,
  outcome_horizon_sessions: 5,
  event_count: 6,
  whipsaw_count: 2,
  whipsaw_rate: 0.4,
  latest_whipsaw_date: "2026-04-22",
  risk_score: 45,
  risk_level: "elevated",
  outcome: {
    horizon_sessions: 5,
    evaluated_events: 5,
    win_count: 3,
    win_rate: 0.6,
    average_directional_return: 0.0123,
    median_directional_return: 0.01,
    p25_directional_return: -0.004,
    p75_directional_return: 0.026,
  },
  recent_events: [
    {
      event_date: "2026-04-22",
      state: "green",
      sessions_since_previous: 2,
      is_whipsaw: true,
      directional_return: 0.018,
    },
  ],
};

vi.mock("recharts", () => ({
  CartesianGrid: () => null,
  Line: () => null,
  LineChart: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  ReferenceDot: () => null,
  ResponsiveContainer: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Tooltip: () => null,
  XAxis: () => null,
  YAxis: () => null,
}));

const watchlistCandidates = {
  generated_at: "2026-05-02T18:00:00Z",
  lanes: [
    {
      id: "bullish_alignment",
      label: "Bullish Alignment",
      description: "Current scores with monthly, weekly, and daily support.",
      candidates: [
        {
          ...latestSignals[0],
          latest_transition_type: "breakout_bullish",
          latest_transition_bar_date: "2026-04-22",
          latest_transition_notes: "daily triangle green",
          sector: "Materials",
          watchlist_signal_count: 4,
          watchlist_last_signal_at: "2026-02-12T17:00:00Z",
          legacy_action: "BUY",
          legacy_signal_type: "Technical",
          legacy_confidence_score: 87,
          legacy_price_target: "84.50",
          legacy_signal_at: "2026-02-12T17:01:00Z",
        },
      ],
    },
    {
      id: "risk_alignment",
      label: "Risk Alignment",
      description: "Current scores that should stay on the risk desk.",
      candidates: [],
    },
    {
      id: "reentry",
      label: "Re-entry",
      description: "Recent bullish turns with non-negative current scores.",
      candidates: [],
    },
    {
      id: "mixed_timeframes",
      label: "Mixed Timeframes",
      description: "Symbols where the timeframes are not in agreement.",
      candidates: [],
    },
  ],
};

const dailyCalibration = {
  parameter_set_name: "dochia_v0_estimated",
  generated_at: "2026-05-02T21:30:00Z",
  since: null,
  until: null,
  total_observations: 24204,
  covered_observations: 22131,
  exact_bar_observations: 22127,
  missing_observations: 2073,
  neutral_generated_observations: 290,
  matches: 13733,
  exact_event_matches: 6130,
  exact_event_accuracy: 0.2771,
  window_event_matches: 9475,
  window_event_accuracy: 0.4281,
  event_window_days: 3,
  no_generated_event_observations: 13800,
  opposite_generated_event_observations: 2201,
  accuracy: 0.6205,
  coverage_rate: 0.9144,
  exact_coverage_rate: 0.9142,
  green_precision: 0.6303,
  green_recall: 0.6351,
  red_precision: 0.6272,
  red_recall: 0.6059,
  score_mae: 43.94,
  score_rmse: 55.74,
  confusion: {
    green: { green: 7060, red: 3967, neutral: 90, missing: 1135 },
    red: { green: 4141, red: 6673, neutral: 200, missing: 938 },
  },
  event_confusion: {
    green: { green: 3100, red: 1010, none: 7007, missing: 1135 },
    red: { green: 1191, red: 3030, none: 6793, missing: 938 },
  },
  top_tickers: [
    {
      ticker: "HUT",
      observations: 143,
      covered_observations: 139,
      exact_bar_observations: 139,
      matches: 85,
      accuracy: 0.6115,
      score_mae: 41.4,
    },
  ],
};

const promotionGate = {
  generated_at: "2026-05-02T22:00:00Z",
  candidate_parameter_set: "dochia_v0_2_range_daily",
  baseline_parameter_set: "dochia_v0_estimated",
  since: null,
  until: null,
  event_window_days: 3,
  production: {
    id: "production",
    label: "Production",
    parameter_set_name: "dochia_v0_estimated",
    daily_trigger_mode: "close",
    latest_bar_date: "2026-04-24",
    signal_count: 120,
    bullish_count: 40,
    risk_count: 20,
    neutral_count: 18,
    reentry_count: 7,
    average_score: 12.5,
    calibration: {
      total_observations: 24204,
      covered_observations: 22131,
      accuracy: 0.6205,
      exact_event_accuracy: 0.2771,
      window_event_accuracy: 0.4281,
      coverage_rate: 0.9144,
      exact_coverage_rate: 0.9142,
      score_mae: 43.94,
      score_rmse: 55.74,
    },
  },
  candidate: {
    id: "candidate",
    label: "v0.2 Range",
    parameter_set_name: "dochia_v0_2_range_daily",
    daily_trigger_mode: "range",
    latest_bar_date: "2026-04-24",
    signal_count: 118,
    bullish_count: 43,
    risk_count: 21,
    neutral_count: 15,
    reentry_count: 9,
    average_score: 14,
    calibration: {
      total_observations: 24204,
      covered_observations: 22131,
      accuracy: 0.6205,
      exact_event_accuracy: 0.3,
      window_event_accuracy: 0.46,
      coverage_rate: 0.9144,
      exact_coverage_rate: 0.9142,
      score_mae: 42,
      score_rmse: 54,
    },
  },
  deltas: {
    window_event_accuracy: 0.0319,
    exact_event_accuracy: 0.0229,
    coverage_rate: 0,
    score_mae: -1.94,
    signal_count: -2,
    reentry_count: 2,
  },
  guardrails: [
    {
      id: "window_event_accuracy",
      label: "Window alert match",
      status: "pass",
      detail: "Candidate should not materially trail production.",
    },
    {
      id: "score_mae",
      label: "Score error",
      status: "pass",
      detail: "Candidate score error should stay close to production.",
    },
  ],
  recommendation: {
    status: "ready_for_shadow",
    label: "Ready for shadow",
    rationale: "Candidate clears the compact promotion gate.",
  },
};

const shadowReview = {
  generated_at: "2026-05-03T18:30:00Z",
  candidate_parameter_set: "dochia_v0_2_range_daily",
  baseline_parameter_set: "dochia_v0_estimated",
  lookback_days: 30,
  review_limit: 8,
  promotion_gate: promotionGate,
  lane_reviews: [
    {
      lane_id: "reentry",
      label: "Re-entry",
      production_tickers: ["AA", "HUT"],
      candidate_tickers: ["AA", "BTU"],
      added_tickers: ["BTU"],
      removed_tickers: ["HUT"],
      unchanged_tickers: ["AA"],
      churn_rate: 2 / 3,
    },
  ],
  transition_pressure: [
    {
      ticker: "AA",
      production_transition_count: 3,
      candidate_transition_count: 5,
      delta: 2,
      latest_candidate_transition_type: "exit_to_reentry",
      latest_candidate_transition_date: "2026-04-22",
    },
  ],
  whipsaw_reviews: [
    {
      ticker: "AA",
      risk_level: "high",
      risk_score: 82,
      event_count: 9,
      whipsaw_count: 5,
      whipsaw_rate: 0.625,
      win_rate: 0.55,
      average_directional_return: 0.01,
      latest_whipsaw_date: "2026-04-23",
    },
  ],
  checklist: [
    {
      id: "promotion_gate",
      label: "Promotion Gate",
      status: "pass",
      detail: "Candidate clears the compact promotion gate.",
    },
    {
      id: "decision_record",
      label: "Human Decision Record",
      status: "blocked",
      detail: "A human promote/defer record is required.",
    },
  ],
  recommendation: {
    status: "needs_review",
    label: "Needs human review",
    rationale: "Evidence is ready, but review pressure remains.",
  },
  decision_record_template: {
    candidate_parameter_set: "dochia_v0_2_range_daily",
    allowed_decisions: ["defer", "continue_shadow", "promote_to_market_signals"],
    required_approver: "Financial operator",
    required_evidence: [
      "Promotion Gate status",
      "Lane churn review",
      "Transition pressure review",
      "Whipsaw/backtest review",
      "Rollback criteria",
    ],
  },
};

const shadowDecisionRecords = [
  {
    id: "33333333-3333-3333-3333-333333333333",
    candidate_parameter_set: "dochia_v0_2_range_daily",
    baseline_parameter_set: "dochia_v0_estimated",
    decision: "continue_shadow",
    reviewer: "Gary Knight",
    rationale: "Keep watching lane churn and whipsaw pressure.",
    rollback_criteria: "Rollback if the promotion gate moves to hold.",
    reviewed_tickers: ["AA", "BTU"],
    notes: "Operator reviewed chart overlays.",
    shadow_review_generated_at: "2026-05-03T18:30:00Z",
    promotion_gate_status: "ready_for_shadow",
    recommendation_status: "needs_review",
    created_at: "2026-05-03T19:00:00Z",
  },
];

const promotionDryRun = {
  generated_at: "2026-05-03T20:30:00Z",
  candidate_parameter_set: "dochia_v0_2_range_daily",
  baseline_parameter_set: "dochia_v0_estimated",
  approval: {
    status: "ready_for_dry_run",
    decision_id: "33333333-3333-3333-3333-333333333333",
    reviewer: "Gary Knight",
    decision_created_at: "2026-05-03T19:00:00Z",
    rollback_criteria: "Rollback if whipsaw pressure rises.",
    detail: "Promote record found; dry-run can be reviewed before any guarded write path.",
  },
  summary: {
    target_table: "hedge_fund.market_signals",
    target_columns: [
      "ticker",
      "signal_type",
      "action",
      "confidence_score",
      "price_target",
      "source_sender",
      "source_subject",
      "raw_reasoning",
      "model_used",
      "extracted_at",
    ],
    write_path_enabled: false,
    candidate_signal_count: 3,
    proposed_insert_count: 2,
    bullish_count: 1,
    risk_count: 1,
    skipped_neutral_count: 1,
    latest_bar_date: "2026-04-24",
    min_abs_score: 50,
  },
  proposed_rows: [
    {
      ticker: "AA",
      action: "BUY",
      signal_type: "Dochia bullish alignment",
      confidence_score: 80,
      price_target: null,
      source_sender: "Dochia Signal Engine",
      source_subject: "Dry-run promotion dochia_v0_2_range_daily",
      raw_reasoning: "Dochia dry-run signal for AA: composite score +80.",
      model_used: "v0.2-candidate",
      extracted_at: "2026-05-02T12:00:00Z",
      candidate_bar_date: "2026-04-24",
      composite_score: 80,
      lineage: {
        source_pipeline: "dochia_signal_scores",
        parameter_set: "dochia_v0_2_range_daily",
        model_version: "v0.2-candidate",
        computed_at: "2026-05-02T12:00:00Z",
        explanation_payload: {
          ticker: "AA",
          composite_score: 80,
        },
        rollback_marker: "dochia-dry-run:dochia_v0_2_range_daily:AA:2026-04-24",
      },
    },
    {
      ticker: "AGIO",
      action: "SELL",
      signal_type: "Dochia risk alignment",
      confidence_score: 80,
      price_target: null,
      source_sender: "Dochia Signal Engine",
      source_subject: "Dry-run promotion dochia_v0_2_range_daily",
      raw_reasoning: "Dochia dry-run signal for AGIO: composite score -80.",
      model_used: "v0.2-candidate",
      extracted_at: "2026-05-02T12:00:00Z",
      candidate_bar_date: "2026-04-24",
      composite_score: -80,
      lineage: {
        source_pipeline: "dochia_signal_scores",
        parameter_set: "dochia_v0_2_range_daily",
        model_version: "v0.2-candidate",
        computed_at: "2026-05-02T12:00:00Z",
        explanation_payload: {
          ticker: "AGIO",
          composite_score: -80,
        },
        rollback_marker: "dochia-dry-run:dochia_v0_2_range_daily:AGIO:2026-04-24",
      },
    },
  ],
};

const promotionDryRunAcceptances = [
  {
    id: "44444444-4444-4444-4444-444444444444",
    decision_record_id: "33333333-3333-3333-3333-333333333333",
    candidate_parameter_set: "dochia_v0_2_range_daily",
    baseline_parameter_set: "dochia_v0_estimated",
    accepted_by: "MarketClub Operator",
    acceptance_rationale: "Accepted after dry-run preview matched the promote record.",
    rollback_criteria: "Rollback if whipsaw pressure rises.",
    dry_run_generated_at: "2026-05-03T20:30:00Z",
    dry_run_candidate_signal_count: 3,
    dry_run_proposed_insert_count: 2,
    dry_run_bullish_count: 1,
    dry_run_risk_count: 1,
    dry_run_skipped_neutral_count: 1,
    min_abs_score: 50,
    target_table: "hedge_fund.market_signals",
    target_columns: [
      "ticker",
      "signal_type",
      "action",
      "confidence_score",
      "price_target",
      "source_sender",
      "source_subject",
      "raw_reasoning",
      "model_used",
      "extracted_at",
    ],
    created_at: "2026-05-03T20:45:00Z",
  },
  {
    id: "77777777-7777-7777-7777-777777777777",
    decision_record_id: "33333333-3333-3333-3333-333333333333",
    candidate_parameter_set: "dochia_v0_2_range_daily",
    baseline_parameter_set: "dochia_v0_estimated",
    accepted_by: "MarketClub Operator",
    acceptance_rationale: "Accepted after a second reviewed dry-run preview cleared the gate.",
    rollback_criteria: "Rollback if whipsaw pressure rises.",
    dry_run_generated_at: "2026-05-03T20:30:00Z",
    dry_run_candidate_signal_count: 3,
    dry_run_proposed_insert_count: 2,
    dry_run_bullish_count: 1,
    dry_run_risk_count: 1,
    dry_run_skipped_neutral_count: 1,
    min_abs_score: 50,
    target_table: "hedge_fund.market_signals",
    target_columns: [
      "ticker",
      "signal_type",
      "action",
      "confidence_score",
      "price_target",
      "source_sender",
      "source_subject",
      "raw_reasoning",
      "model_used",
      "extracted_at",
    ],
    created_at: "2026-05-04T12:45:00Z",
  },
];

const promotionExecutions = [
  {
    id: "55555555-5555-5555-5555-555555555555",
    acceptance_id: "44444444-4444-4444-4444-444444444444",
    decision_record_id: "33333333-3333-3333-3333-333333333333",
    candidate_parameter_set: "dochia_v0_2_range_daily",
    baseline_parameter_set: "dochia_v0_estimated",
    operator_membership_id: "66666666-6666-6666-6666-666666666666",
    executed_by: "MarketClub Operator",
    execution_rationale: "Operator accepted the verified dry-run output.",
    idempotency_key: "operator-accepted-dry-run-20260504",
    dry_run_generated_at: "2026-05-03T20:30:00Z",
    dry_run_proposed_insert_count: 2,
    verification_status: "PASS",
    inserted_market_signal_ids: [1201, 1202],
    rollback_markers: ["dochia-dry-run:dochia_v0_2_range_daily:AA:2026-04-24"],
    rollback_status: "active",
    rollback_operator_membership_id: null,
    rollback_by: null,
    rollback_reason: null,
    rolled_back_at: null,
    created_at: "2026-05-04T12:52:00Z",
  },
];

const promotionRollbackDrills = [
  {
    execution_id: "55555555-5555-5555-5555-555555555555",
    dry_run_acceptance_id: "44444444-4444-4444-4444-444444444444",
    candidate_parameter_set: "dochia_v0_2_range_daily",
    baseline_parameter_set: "dochia_v0_estimated",
    executed_by: "MarketClub Operator",
    executed_at: "2026-05-04T12:52:00Z",
    inserted_market_signal_ids: [1201, 1202],
    rollback_markers: ["dochia-dry-run:dochia_v0_2_range_daily:AA:2026-04-24"],
    audited_market_signal_ids: [1201, 1202],
    rollback_preview_market_signal_ids: [1201, 1202],
    rollback_preview_count: 2,
    rollback_eligibility: "ELIGIBLE",
    rollback_eligible: true,
    already_rolled_back: false,
    rollback_status: "active",
    rollback_by: null,
    rollback_attempted_at: null,
    rolled_back_at: null,
  },
];

const promotionDryRunVerification = {
  generated_at: "2026-05-03T20:31:00Z",
  candidate_parameter_set: "dochia_v0_2_range_daily",
  production_parameter_set: "dochia_v0_estimated",
  overall_status: "PASS",
  proposed_rows_checked: 2,
  passed_rows: 2,
  failed_rows: 0,
  inconclusive_rows: 0,
  cross_model_diagnostic_only_rows: 1,
  rows: [
    {
      row_status: "PASS",
      ticker: "ACLX",
      candidate_bar_date: "2026-04-24",
      candidate_score: 80,
      candidate_action: "BUY",
      candidate_monthly_triangle: 1,
      candidate_weekly_triangle: 1,
      candidate_daily_triangle: 1,
      latest_candidate_transition_date: "2026-04-23",
      latest_candidate_transition_type: "breakout_bullish",
      prior_score: 50,
      new_score: 80,
      production_score: 50,
      production_daily_triangle: -1,
      conflict_type: "CROSS_MODEL_DIAGNOSTIC_ONLY",
      explanation: "Production baseline differs from candidate, but candidate lineage is clean.",
    },
  ],
};

let promotionDryRunAcceptancesMock = promotionDryRunAcceptances;
let promotionExecutionsMock = promotionExecutions;
let promotionDryRunVerificationMock = promotionDryRunVerification;

vi.mock("@/lib/hooks", () => ({
  useFinancialLatestSignals: () => ({
    data: latestSignals,
    isError: false,
    isFetching: false,
    isLoading: false,
    refetch: vi.fn(),
  }),
  useFinancialSignalTransitions: () => ({
    data: transitions,
    isError: false,
    isFetching: false,
    isLoading: false,
    refetch: vi.fn(),
  }),
  useFinancialSignalDetail: () => ({
    data: {
      ticker: "AA",
      latest: latestSignals[0],
      recent_transitions: transitions,
    },
    isFetching: false,
    isLoading: false,
    refetch: vi.fn(),
  }),
  useFinancialSignalChart: () => ({
    data: chartData,
    isError: false,
    isFetching: false,
    isLoading: false,
    refetch: vi.fn(),
  }),
  useFinancialWhipsawRisk: () => ({
    data: whipsawRisk,
    isError: false,
    isFetching: false,
    isLoading: false,
    refetch: vi.fn(),
  }),
  useFinancialWatchlistCandidates: () => ({
    data: watchlistCandidates,
    isError: false,
    isFetching: false,
    isLoading: false,
    refetch: vi.fn(),
  }),
  useFinancialDailyCalibration: () => ({
    data: dailyCalibration,
    isError: false,
    isFetching: false,
    isLoading: false,
    refetch: vi.fn(),
  }),
  useFinancialPromotionGate: () => ({
    data: promotionGate,
    isError: false,
    isFetching: false,
    isLoading: false,
    refetch: vi.fn(),
  }),
  useFinancialShadowReview: () => ({
    data: shadowReview,
    isError: false,
    isFetching: false,
    isLoading: false,
    refetch: vi.fn(),
  }),
  useFinancialShadowDecisionRecords: () => ({
    data: shadowDecisionRecords,
    isError: false,
    isFetching: false,
    isLoading: false,
    refetch: vi.fn(),
  }),
  useFinancialPromotionDryRun: () => ({
    data: promotionDryRun,
    isError: false,
    isFetching: false,
    isLoading: false,
    refetch: vi.fn(),
  }),
  useFinancialPromotionDryRunVerification: () => ({
    data: promotionDryRunVerificationMock,
    isError: false,
    isFetching: false,
    isLoading: false,
    refetch: vi.fn(),
  }),
  useFinancialPromotionDryRunAcceptances: () => ({
    data: promotionDryRunAcceptancesMock,
    isError: false,
    isFetching: false,
    isLoading: false,
    refetch: vi.fn(),
  }),
  useFinancialPromotionExecutions: () => ({
    data: promotionExecutionsMock,
    isError: false,
    isFetching: false,
    isLoading: false,
    refetch: vi.fn(),
  }),
  useFinancialPromotionRollbackDrills: () => ({
    data: promotionRollbackDrills,
    isError: false,
    isFetching: false,
    isLoading: false,
    refetch: vi.fn(),
  }),
  useCreateFinancialShadowDecisionRecord: () => ({
    isPending: false,
    mutateAsync: vi.fn(),
  }),
  useCreateFinancialPromotionDryRunAcceptance: () => ({
    isPending: false,
    mutateAsync: vi.fn(),
  }),
  useExecuteFinancialPromotionDryRunAcceptance: () => ({
    isPending: false,
    mutateAsync: vi.fn(),
  }),
  useRollbackFinancialPromotionExecution: () => ({
    isPending: false,
    mutateAsync: vi.fn(),
  }),
}));

describe("HedgeFundSignalsShell", () => {
  beforeEach(() => {
    promotionDryRunAcceptancesMock = promotionDryRunAcceptances;
    promotionExecutionsMock = promotionExecutions;
    promotionDryRunVerificationMock = promotionDryRunVerification;
  });

  it("renders latest signals, score context, and transition feed", () => {
    render(<HedgeFundSignalsShell />);

    expect(screen.getByRole("heading", { name: "Hedge Fund Signals" })).toBeInTheDocument();
    expect(screen.getByText("Signal Scanner")).toBeInTheDocument();
    expect(screen.getAllByText("AA").length).toBeGreaterThan(0);
    expect(screen.getAllByText("AGIO").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Bullish break").length).toBeGreaterThan(0);
    expect(screen.getByText("Score Distribution")).toBeInTheDocument();
    expect(screen.getByText("Portfolio Lens")).toBeInTheDocument();
    expect(screen.getAllByText("BUY").length).toBeGreaterThan(0);
    expect(screen.getByText("Calibration Baseline")).toBeInTheDocument();
    expect(screen.getByText("62.1%")).toBeInTheDocument();
    expect(screen.getAllByText("Promotion Gate").length).toBeGreaterThan(0);
    expect(screen.getByText("Ready for shadow")).toBeInTheDocument();
    expect(screen.getByText("Production vs v0.2 Range")).toBeInTheDocument();
    expect(screen.getByText("Shadow Review")).toBeInTheDocument();
    expect(screen.getByText("Needs human review")).toBeInTheDocument();
    expect(screen.getByText("Lane Churn")).toBeInTheDocument();
    expect(screen.getByText("Human Decision Record")).toBeInTheDocument();
    expect(screen.getByText("Decision Record")).toBeInTheDocument();
    expect(screen.getByText("Decision Records")).toBeInTheDocument();
    expect(screen.getAllByText("Continue shadow").length).toBeGreaterThan(0);
    expect(screen.getByText("Promotion Dry-Run")).toBeInTheDocument();
    expect(screen.getByText("market_signals Preview")).toBeInTheDocument();
    expect(screen.getByText("Ready for dry-run")).toBeInTheDocument();
    expect(screen.getByText("hedge_fund.market_signals")).toBeInTheDocument();
    expect(screen.getByText("Dry-Run Verification Gate")).toBeInTheDocument();
    expect(screen.getByText("Eligible for operator dry-run acceptance review")).toBeInTheDocument();
    expect(screen.getByText("CROSS_MODEL_DIAGNOSTIC_ONLY")).toBeInTheDocument();
    expect(screen.getByText("Dry-Run Acceptance")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Accept Dry-Run" })).toBeInTheDocument();
    expect(screen.getByText("2 saved")).toBeInTheDocument();
    expect(screen.getByText("Operator Execution")).toBeInTheDocument();
    expect(screen.getByLabelText("Execution Operator Token")).toBeInTheDocument();
    expect(screen.getByLabelText("Execution Rationale")).toBeInTheDocument();
    expect(screen.getByLabelText("Execution Idempotency Key")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Execute accepted dry-run" })).toBeDisabled();
    expect(screen.getByText("Execution Records")).toBeInTheDocument();
    expect(screen.getByText("1 recorded")).toBeInTheDocument();
    expect(screen.getByText("Inserted rows")).toBeInTheDocument();
    expect(screen.getByText("Rollback Drill")).toBeInTheDocument();
    expect(screen.getByText("1 checked")).toBeInTheDocument();
    expect(screen.getByText("Dry-run acceptance ID")).toBeInTheDocument();
    expect(screen.getByText("Rollback preview count")).toBeInTheDocument();
    expect(screen.getByText("Inserted market_signal IDs")).toBeInTheDocument();
    expect(screen.getByText("1201, 1202")).toBeInTheDocument();
    expect(screen.getByText("Already rolled back")).toBeInTheDocument();
    expect(screen.getByText("No")).toBeInTheDocument();
    expect(screen.getByLabelText("Operator Token")).toBeInTheDocument();
    expect(screen.getByLabelText("Rollback Reason")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Roll back execution" })).toBeDisabled();
    expect(screen.getAllByText("Active").length).toBeGreaterThan(0);
    expect(
      screen.getAllByText("dochia-dry-run:dochia_v0_2_range_daily:AA:2026-04-24").length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByText("MarketClub Operator").length).toBeGreaterThan(0);
    expect(screen.getByText("Chart Overlay")).toBeInTheDocument();
    expect(screen.getByText("1 triangle events")).toBeInTheDocument();
    expect(screen.getByText("Whipsaw Risk / Backtest")).toBeInTheDocument();
    expect(screen.getByText("Elevated")).toBeInTheDocument();
    expect(screen.getByText("60.0%")).toBeInTheDocument();
    expect(screen.getAllByText("dochia_v0_estimated").length).toBeGreaterThan(0);
  });

  it("switches the internal signal model badge without leaving the page", () => {
    render(<HedgeFundSignalsShell />);

    fireEvent.click(screen.getByRole("button", { name: "v0.2 Range" }));

    expect(screen.getByText("dochia_v0_2_range_daily")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "v0.2 Range" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("hides the execution action when the gate fails or every acceptance has executed", () => {
    promotionDryRunVerificationMock = {
      ...promotionDryRunVerification,
      overall_status: "FAIL",
      failed_rows: 1,
      passed_rows: 1,
    };

    const { unmount } = render(<HedgeFundSignalsShell />);

    expect(screen.queryByRole("button", { name: "Execute accepted dry-run" })).not.toBeInTheDocument();
    unmount();

    promotionDryRunVerificationMock = promotionDryRunVerification;
    promotionDryRunAcceptancesMock = [promotionDryRunAcceptances[0]];
    promotionExecutionsMock = promotionExecutions;

    render(<HedgeFundSignalsShell />);

    expect(screen.queryByRole("button", { name: "Execute accepted dry-run" })).not.toBeInTheDocument();
  });
});
