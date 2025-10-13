-- Migration: Add Professional Enhancement Fields to signals table
-- Run this ONCE to upgrade existing database

-- Multi-Timeframe Context
ALTER TABLE signals ADD COLUMN context_timeframe VARCHAR(10);
ALTER TABLE signals ADD COLUMN signal_timeframe VARCHAR(10);
ALTER TABLE signals ADD COLUMN confirmation_timeframe VARCHAR(10);

-- Signal Confluence
ALTER TABLE signals ADD COLUMN confluence_count INTEGER DEFAULT 1;
ALTER TABLE signals ADD COLUMN confluence_strategies TEXT;
ALTER TABLE signals ADD COLUMN confluence_bonus FLOAT DEFAULT 0.0;

-- Structure-Based SL/TP Sources
ALTER TABLE signals ADD COLUMN sl_type VARCHAR(30);
ALTER TABLE signals ADD COLUMN sl_level FLOAT;
ALTER TABLE signals ADD COLUMN sl_offset FLOAT;
ALTER TABLE signals ADD COLUMN tp1_type VARCHAR(30);
ALTER TABLE signals ADD COLUMN tp2_type VARCHAR(30);

-- MAE/MFE Tracking
ALTER TABLE signals ADD COLUMN max_favorable_excursion FLOAT;
ALTER TABLE signals ADD COLUMN max_adverse_excursion FLOAT;
ALTER TABLE signals ADD COLUMN bars_to_tp1 INTEGER;
ALTER TABLE signals ADD COLUMN bars_to_exit INTEGER;

-- Partial Profit Taking (30/40/30)
ALTER TABLE signals ADD COLUMN tp1_size FLOAT DEFAULT 0.30;
ALTER TABLE signals ADD COLUMN tp2_size FLOAT DEFAULT 0.40;
ALTER TABLE signals ADD COLUMN runner_size FLOAT DEFAULT 0.30;

ALTER TABLE signals ADD COLUMN tp1_pnl_percent FLOAT;
ALTER TABLE signals ADD COLUMN tp2_hit BOOLEAN DEFAULT 0;
ALTER TABLE signals ADD COLUMN tp2_closed_at DATETIME;
ALTER TABLE signals ADD COLUMN tp2_pnl_percent FLOAT;

-- Trailing Stop for Runner
ALTER TABLE signals ADD COLUMN trailing_active BOOLEAN DEFAULT 0;
ALTER TABLE signals ADD COLUMN trailing_high_water_mark FLOAT;
ALTER TABLE signals ADD COLUMN runner_exit_price FLOAT;
ALTER TABLE signals ADD COLUMN runner_pnl_percent FLOAT;

-- Add composite index for regime+confluence analysis
CREATE INDEX IF NOT EXISTS idx_regime_confidence ON signals(market_regime, confluence_count);

-- MIGRATION COMPLETE
-- New signals will automatically use these fields
-- Existing signals will have NULL values (which is OK for analysis)
