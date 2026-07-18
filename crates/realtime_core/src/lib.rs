pub fn volume_spike_ratio(latest: f64, baseline: f64) -> f64 {
    if baseline <= 0.0 {
        return 1.0;
    }
    latest / baseline
}

pub fn average_absolute_return(prices: &[f64]) -> f64 {
    if prices.len() < 2 {
        return 0.0;
    }

    let mut total = 0.0;
    let mut count = 0.0;

    for pair in prices.windows(2) {
        let previous = pair[0];
        let current = pair[1];
        if previous > 0.0 {
            total += ((current - previous) / previous).abs();
            count += 1.0;
        }
    }

    if count == 0.0 { 0.0 } else { total / count }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn calculates_volume_spike_ratio() {
        assert_eq!(volume_spike_ratio(300.0, 100.0), 3.0);
        assert_eq!(volume_spike_ratio(300.0, 0.0), 1.0);
    }

    #[test]
    fn calculates_average_absolute_return() {
        let value = average_absolute_return(&[100.0, 110.0, 99.0]);
        assert!((value - 0.1).abs() < 0.0001);
    }
}
