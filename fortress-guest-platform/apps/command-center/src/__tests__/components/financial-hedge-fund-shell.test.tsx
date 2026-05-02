import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

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
  useFinancialWatchlistCandidates: () => ({
    data: watchlistCandidates,
    isError: false,
    isFetching: false,
    isLoading: false,
    refetch: vi.fn(),
  }),
}));

describe("HedgeFundSignalsShell", () => {
  it("renders latest signals, score context, and transition feed", () => {
    render(<HedgeFundSignalsShell />);

    expect(screen.getByRole("heading", { name: "Hedge Fund Signals" })).toBeInTheDocument();
    expect(screen.getByText("Signal Scanner")).toBeInTheDocument();
    expect(screen.getAllByText("AA").length).toBeGreaterThan(0);
    expect(screen.getByText("AGIO")).toBeInTheDocument();
    expect(screen.getAllByText("Bullish break").length).toBeGreaterThan(0);
    expect(screen.getByText("Score Distribution")).toBeInTheDocument();
    expect(screen.getByText("Portfolio Lens")).toBeInTheDocument();
    expect(screen.getByText("BUY")).toBeInTheDocument();
  });
});
