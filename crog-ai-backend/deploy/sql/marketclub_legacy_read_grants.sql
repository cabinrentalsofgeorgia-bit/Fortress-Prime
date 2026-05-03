GRANT USAGE ON SCHEMA hedge_fund TO crog_ai_app;
GRANT SELECT ON TABLE
    hedge_fund.watchlist,
    hedge_fund.market_signals,
    hedge_fund.active_strategies
TO crog_ai_app;

GRANT SELECT, INSERT ON TABLE
    hedge_fund.signal_shadow_review_decisions,
    hedge_fund.signal_promotion_dry_run_acceptances
TO crog_ai_app;
