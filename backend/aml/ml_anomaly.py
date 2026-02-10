"""ML-based anomaly detection for AML pipeline.

Uses Isolation Forest (sklearn) when available, with a pure-Python
statistical fallback (Mahalanobis-like distance on feature vectors).

Features per transaction:
- amount (log-scaled)
- day_of_week (0-6)
- day_of_month (1-31)
- channel (one-hot encoded)
- is_new_counterparty (0/1)
- direction (0=CREDIT, 1=DEBIT)
- counterparty_frequency (how often seen)
"""

from __future__ import annotations

import logging
import math
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from .normalize import NormalizedTransaction

log = logging.getLogger("aistate.aml.ml_anomaly")

CHANNELS = ["CARD", "TRANSFER", "BLIK_P2P", "BLIK_MERCHANT", "CASH", "FEE", "OTHER"]


def _build_features(
    transactions: List[NormalizedTransaction],
    known_counterparties: Optional[Set[str]] = None,
) -> Tuple[List[List[float]], List[str]]:
    """Build feature vectors for each transaction.

    Returns:
        (feature_matrix, tx_ids)
    """
    if known_counterparties is None:
        known_counterparties = set()

    # Pre-compute counterparty frequencies
    cp_counts: Counter = Counter()
    for tx in transactions:
        cp = (tx.counterparty_clean or "").lower()[:50]
        if cp:
            cp_counts[cp] += 1

    max_cp_freq = max(cp_counts.values()) if cp_counts else 1
    channel_idx = {ch: i for i, ch in enumerate(CHANNELS)}

    features = []
    tx_ids = []

    for tx in transactions:
        amt = float(abs(tx.amount))
        log_amt = math.log1p(amt)

        # Date features
        dow = 3  # default Wednesday
        dom = 15  # default mid-month
        if tx.booking_date and len(tx.booking_date) >= 10:
            try:
                from datetime import datetime
                dt = datetime.strptime(tx.booking_date[:10], "%Y-%m-%d")
                dow = dt.weekday()
                dom = dt.day
            except ValueError:
                pass

        # Channel one-hot
        ch_vec = [0.0] * len(CHANNELS)
        ch_i = channel_idx.get(tx.channel, len(CHANNELS) - 1)
        ch_vec[ch_i] = 1.0

        # New counterparty
        cp = (tx.counterparty_clean or "").lower()[:50]
        is_new = 1.0 if cp and cp not in known_counterparties else 0.0

        # Direction
        direction = 1.0 if tx.direction == "DEBIT" else 0.0

        # Counterparty frequency (normalized)
        cp_freq = cp_counts.get(cp, 0) / max_cp_freq if max_cp_freq > 0 else 0

        vec = [log_amt, dow / 6.0, dom / 31.0, direction, is_new, cp_freq] + ch_vec
        features.append(vec)
        tx_ids.append(tx.id)

    return features, tx_ids


def detect_ml_anomalies(
    transactions: List[NormalizedTransaction],
    known_counterparties: Optional[Set[str]] = None,
    contamination: float = 0.05,
) -> List[Dict[str, Any]]:
    """Detect anomalies using ML (Isolation Forest or statistical fallback).

    Returns list of dicts: {tx_id, anomaly_score, is_anomaly, features}
    """
    if len(transactions) < 10:
        return []

    features, tx_ids = _build_features(transactions, known_counterparties)

    # Try sklearn first
    try:
        return _detect_with_sklearn(features, tx_ids, contamination)
    except ImportError:
        log.info("sklearn not available, using statistical fallback")
    except Exception as e:
        log.warning("sklearn anomaly detection failed: %s", e)

    # Fallback: pure Python statistical detection
    return _detect_statistical(features, tx_ids, contamination)


def _detect_with_sklearn(
    features: List[List[float]],
    tx_ids: List[str],
    contamination: float,
) -> List[Dict[str, Any]]:
    """Use sklearn IsolationForest."""
    import numpy as np
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler

    X = np.array(features)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    clf = IsolationForest(
        contamination=contamination,
        random_state=42,
        n_estimators=100,
    )
    clf.fit(X_scaled)
    predictions = clf.predict(X_scaled)   # -1 = anomaly, 1 = normal
    scores = clf.decision_function(X_scaled)  # lower = more anomalous

    results = []
    for i, tx_id in enumerate(tx_ids):
        is_anomaly = predictions[i] == -1
        # Normalize score to 0-1 (higher = more anomalous)
        raw_score = -scores[i]
        norm_score = max(0, min(1, (raw_score + 0.5) / 1.0))

        results.append({
            "tx_id": tx_id,
            "anomaly_score": round(float(norm_score), 3),
            "is_anomaly": bool(is_anomaly),
        })

    return results


def _detect_statistical(
    features: List[List[float]],
    tx_ids: List[str],
    contamination: float,
) -> List[Dict[str, Any]]:
    """Pure Python statistical anomaly detection.

    Uses z-score distance from centroid across all features.
    """
    n = len(features)
    dim = len(features[0]) if features else 0
    if n < 5 or dim == 0:
        return []

    # Compute mean and std for each feature
    means = [0.0] * dim
    for vec in features:
        for j in range(dim):
            means[j] += vec[j]
    means = [m / n for m in means]

    stds = [0.0] * dim
    for vec in features:
        for j in range(dim):
            stds[j] += (vec[j] - means[j]) ** 2
    stds = [math.sqrt(s / max(n - 1, 1)) for s in stds]

    # Compute distance from centroid for each transaction
    distances = []
    for vec in features:
        d = 0.0
        for j in range(dim):
            if stds[j] > 1e-9:
                d += ((vec[j] - means[j]) / stds[j]) ** 2
        distances.append(math.sqrt(d / dim))

    # Determine threshold from contamination percentage
    sorted_dists = sorted(distances)
    threshold_idx = int((1 - contamination) * n)
    threshold = sorted_dists[min(threshold_idx, n - 1)]

    results = []
    max_dist = max(distances) if distances else 1
    for i, tx_id in enumerate(tx_ids):
        is_anomaly = distances[i] > threshold
        norm_score = distances[i] / max_dist if max_dist > 0 else 0

        results.append({
            "tx_id": tx_id,
            "anomaly_score": round(norm_score, 3),
            "is_anomaly": is_anomaly,
        })

    return results
