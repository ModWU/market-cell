#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MarketType {
    Spot,
    PerpetualFuture,
    Futures,
    Index,
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TradeSide {
    Buy,
    Sell,
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SourceState {
    Connecting,
    Healthy,
    Degraded,
    Stale,
    Down,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum QualityIssue {
    EmptySymbol,
    EmptyInterval,
    InvalidTimeRange,
    NonFinitePrice,
    NonFiniteVolume,
    NonPositivePrice,
    NegativeVolume,
    InvalidPriceRange,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Candle {
    pub source_provider: String,
    pub exchange: String,
    pub symbol: String,
    pub market_type: MarketType,
    pub interval: String,
    pub open_time_ms: i64,
    pub close_time_ms: i64,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub volume: f64,
    pub trade_count: Option<u64>,
    pub quote_volume: Option<f64>,
    pub fetched_at_ms: Option<i64>,
    pub quality_flags: Vec<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct TradeTick {
    pub source_provider: String,
    pub exchange: String,
    pub symbol: String,
    pub market_type: MarketType,
    pub event_time_ms: i64,
    pub trade_id: Option<String>,
    pub price: f64,
    pub quantity: f64,
    pub side: TradeSide,
}

#[derive(Debug, Clone, PartialEq)]
pub struct SourceStatus {
    pub source_provider: String,
    pub state: SourceState,
    pub observed_at_ms: i64,
    pub latency_ms: Option<u64>,
    pub message: Option<String>,
}

impl Candle {
    pub fn validation_issues(&self) -> Vec<QualityIssue> {
        let mut issues = Vec::new();

        if self.symbol.trim().is_empty() {
            issues.push(QualityIssue::EmptySymbol);
        }
        if self.interval.trim().is_empty() {
            issues.push(QualityIssue::EmptyInterval);
        }
        if self.open_time_ms >= self.close_time_ms {
            issues.push(QualityIssue::InvalidTimeRange);
        }
        if !self.open.is_finite()
            || !self.high.is_finite()
            || !self.low.is_finite()
            || !self.close.is_finite()
        {
            issues.push(QualityIssue::NonFinitePrice);
        }
        if self.open <= 0.0 || self.high <= 0.0 || self.low <= 0.0 || self.close <= 0.0 {
            issues.push(QualityIssue::NonPositivePrice);
        }
        if !self.volume.is_finite() {
            issues.push(QualityIssue::NonFiniteVolume);
        } else if self.volume < 0.0 {
            issues.push(QualityIssue::NegativeVolume);
        }
        if self.high < self.low
            || self.high < self.open.max(self.close)
            || self.low > self.open.min(self.close)
        {
            issues.push(QualityIssue::InvalidPriceRange);
        }

        issues
    }
}

pub fn is_valid_candle(candle: &Candle) -> bool {
    candle.validation_issues().is_empty()
}

pub fn volume_spike_ratio(latest: f64, baseline: f64) -> f64 {
    if !latest.is_finite() || !baseline.is_finite() || baseline <= 0.0 {
        return 1.0;
    }
    latest / baseline
}

pub fn candle_range_pct(candle: &Candle) -> f64 {
    if candle.close <= 0.0
        || !candle.close.is_finite()
        || !candle.high.is_finite()
        || !candle.low.is_finite()
    {
        return 0.0;
    }
    (candle.high - candle.low) / candle.close * 100.0
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_candle() -> Candle {
        Candle {
            source_provider: "binance".to_string(),
            exchange: "binance".to_string(),
            symbol: "BTCUSDT".to_string(),
            market_type: MarketType::Spot,
            interval: "1m".to_string(),
            open_time_ms: 1_720_000_000_000,
            close_time_ms: 1_720_000_059_999,
            open: 100.0,
            high: 105.0,
            low: 99.0,
            close: 103.0,
            volume: 12.5,
            trade_count: Some(100),
            quote_volume: Some(1_250.0),
            fetched_at_ms: Some(1_720_000_060_000),
            quality_flags: Vec::new(),
        }
    }

    #[test]
    fn validates_a_well_formed_candle() {
        let candle = sample_candle();

        assert!(is_valid_candle(&candle));
        assert!(candle.validation_issues().is_empty());
    }

    #[test]
    fn rejects_invalid_ohlcv_values() {
        let mut candle = sample_candle();
        candle.high = 98.0;
        candle.volume = -1.0;

        let issues = candle.validation_issues();

        assert!(!is_valid_candle(&candle));
        assert!(issues.contains(&QualityIssue::InvalidPriceRange));
        assert!(issues.contains(&QualityIssue::NegativeVolume));
    }

    #[test]
    fn rejects_non_finite_volume_separately() {
        let mut candle = sample_candle();
        candle.volume = f64::NAN;

        let issues = candle.validation_issues();

        assert!(issues.contains(&QualityIssue::NonFiniteVolume));
        assert!(!issues.contains(&QualityIssue::NegativeVolume));
    }

    #[test]
    fn calculates_range_percent_against_close() {
        let candle = sample_candle();
        let value = candle_range_pct(&candle);

        assert!((value - 5.825242718).abs() < 0.000001);
    }

    #[test]
    fn calculates_volume_spike_ratio_with_stable_fallback() {
        assert_eq!(volume_spike_ratio(300.0, 100.0), 3.0);
        assert_eq!(volume_spike_ratio(300.0, 0.0), 1.0);
        assert_eq!(volume_spike_ratio(f64::NAN, 100.0), 1.0);
    }
}
