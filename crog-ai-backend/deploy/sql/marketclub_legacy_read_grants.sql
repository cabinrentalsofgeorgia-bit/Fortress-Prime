GRANT USAGE ON SCHEMA hedge_fund TO crog_ai_app;
GRANT SELECT ON TABLE
    hedge_fund.watchlist,
    hedge_fund.market_signals,
    hedge_fund.active_strategies
TO crog_ai_app;
