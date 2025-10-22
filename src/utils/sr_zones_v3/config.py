"""
V3 Configuration - Default parameters from professional methodology
All parameters tunable via config.yaml
"""

V3_DEFAULT_CONFIG = {
    # Fractal parameters by timeframe
    'fractal_k': {
        '1d': 4,
        '4h': 3,
        '1h': 3,
        '15m': 2,
    },
    
    # DBSCAN clustering
    'clustering': {
        'epsilon_atr_mult': 0.6,  # ε = 0.6 * ATR_TF
        'min_samples': 2,
    },
    
    # Zone width by timeframe (clamp range in ATR multiples)
    'zone_width': {
        '1d': {'min': 0.8, 'max': 1.6},
        '4h': {'min': 0.6, 'max': 1.2},
        '1h': {'min': 0.5, 'max': 1.0},
        '15m': {'min': 0.35, 'max': 0.7},
        'min_pct': 0.001,  # 0.1% minimum width
    },
    
    # Valid reaction thresholds
    'reaction': {
        'atr_mult': 0.7,  # Minimum reaction ≥0.7 ATR
        'bars_window': {
            '1d': 5,
            '4h': 6,
            '1h': 8,
            '15m': 12,
        },
    },
    
    # Flip (breakout) detection
    'flip': {
        'body_break_atr': 0.3,  # b1 = 0.3 * ATR - минимальный пробой телом
        'confirmation_bars': 2,  # N = 2 bars - баров подряд для подтверждения
        'retest_reaction_atr': 0.4,  # r2 = 0.4 ATR - минимальная реакция при ретесте
        'weight_multiplier': 0.6,  # Old score × 0.6 after flip
        
        # Альтернативное подтверждение: 1 закрытие + ретест
        'retest_lookforward_bars': 12,  # N = 12 баров для поиска ретеста
        'retest_accept_delta_atr': 0.25,  # Допуск для ретеста (0.25 × ATR от края зоны)
    },
    
    # Freshness decay (exponential) by timeframe
    # ✅ OPTIMIZED (October 2025): Смягчены для сохранения качественных старых зон
    'freshness': {
        'tau_days': {
            '1d': 40,
            '4h': 25,
            '1h': 15,
            '15m': 7,
        }
    },
    
    # Multi-TF merge
    'merge': {
        'overlap_threshold': 0.40,  # 40% overlap to merge
    },
    
    # Scoring weights (w1..w5)
    # ✅ OPTIMIZED (October 2025): Оптимизированы на основе industry best practices
    'scoring': {
        'w1_touches': 22,      # 20% (было 24%) - снижен, 2-3 касания достаточно
        'w2_reactions': 32,    # 30% (было 28%) - увеличен, самый важный фактор!
        'w3_freshness': 16,    # 15% (было 18%) - снижен, старые зоны не так плохи
        'w4_confluence': 24,   # 22% (было 22%) - увеличен, теперь реально работает
        'w5_noise': 14,        # 13% (было 12%) - увеличен penalty за шум
    },
    
    # Strength classification thresholds
    'strength_classes': {
        'key': 80,      # ≥80 = "key"
        'strong': 60,   # 60-79 = "strong"
        'normal': 40,   # 40-59 = "normal"
        # <40 = "weak"
    },
    
    # Zone lifecycle (Candidate → Active → Key)
    'lifecycle': {
        # Candidate → Active requirements
        'active': {
            'min_touches': 2,        # Минимум 2 валидных касания
            'min_purity': 0.65,      # Purity ≥ 0.65
            'require_fresh': True,   # Freshness соблюдена (stale=False)
        },
        # Active → Key requirements
        'key': {
            'min_score': 80,          # Score ≥ 80
            'require_htf_or_reactions': True,  # HTF overlap ИЛИ ≥3 реакций
            'min_reactions_alt': 3,   # Альтернатива HTF: ≥3 валидных реакций
        },
        # Hysteresis (антимигание)
        'hysteresis': {
            'demote_to_normal_score': 50,   # Снизить в normal если score < 50
            'demote_to_normal_purity': 0.60,  # Или если purity < 0.60
        },
    },
    
    # Auto-pruning (удаление старых зон)
    'pruning': {
        # Drop zones если нет касаний дольше чем X дней
        'drop_if_no_touch_days': {
            '15m': 3,
            '1h': 7,
            '4h': 14,
            '1d': 30,
        },
        # Recreate cooldown (баров) - не создавать зону в той же области
        'recreate_cooldown_bars': {
            '15m': 30,
            '1h': 24,
            '4h': 18,
            '1d': 12,
        },
        # Decay rate для strength (экспоненциальный если нет касаний)
        'strength_decay_per_day': 0.05,  # -5% strength per day без касаний
    },
    
    # Zone Selector (вместо простого Top-N)
    'selector': {
        # Hard caps per TF
        'hard_caps': {
            '15m': 15,
            '1h': 15,
            '4h': 12,
            '1d': 10,
        },
        # Per-range cap (zones per ATR bucket)
        'per_range_cap': 2,          # Макс 2 зоны на корзину
        'atr_bucket_size': 1.0,      # Корзина = 1.0 × ATR
        
        # Min spacing multipliers (by TF)
        'min_spacing_mult': {
            '15m': 0.4,  # 0.4 × ATR
            '1h': 0.5,   # 0.5 × ATR
            '4h': 0.6,   # 0.6 × ATR
            '1d': 0.7,   # 0.7 × ATR
        },
        
        # KDE prominence threshold (final filter if over limit)
        'kde_prominence_threshold': 0.25,
    },
    
    # Zone expiry (no touches in T days)
    'expiry_days': {
        '1d': 60,
        '4h': 30,
        '1h': 15,
        '15m': 5,
    },
    
    # Confluence detection
    'confluence': {
        'ema200_proximity_atr': 0.5,  # Within 0.5 ATR of EMA200
        'round_number_tolerance_pct': 0.002,  # ±0.2% for round numbers
    }
}


def get_config(key_path: str, tf: str = None, default=None):
    """
    Получить конфиг параметр по пути
    
    Args:
        key_path: Путь вида 'fractal_k' или 'zone_width.min'
        tf: Таймфрейм ('1d', '4h', '1h', '15m') если параметр TF-зависимый
        default: Значение по умолчанию если не найдено
    
    Returns:
        Значение параметра
    """
    keys = key_path.split('.')
    value = V3_DEFAULT_CONFIG
    
    for key in keys:
        value = value.get(key)
        if value is None:
            return default
    
    # Если параметр TF-зависимый
    if isinstance(value, dict) and tf and tf in value:
        return value[tf]
    
    return value if value is not None else default
