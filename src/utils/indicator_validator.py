from typing import Dict, List
from src.utils.logger import logger


class IndicatorValidator:
    """
    Валидация качества индикаторов для стратегий
    Проверяет что критичные индикаторы не равны заглушкам и содержат реальные данные
    """
    
    # Критичные индикаторы и их флаги валидности
    CRITICAL_INDICATORS = {
        'doi_pct': {
            'type': 'float',
            'validity_flag': 'oi_data_valid',  # Флаг валидности данных
            'description': 'Open Interest Delta %',
            'required_for': ['Liquidity Sweep', 'Order Flow', 'Volume Profile']
        },
        'depth_imbalance': {
            'type': 'float',
            'validity_flag': 'depth_data_valid',  # Флаг валидности данных
            'description': 'Orderbook Depth Imbalance',
            'required_for': ['Liquidity Sweep', 'Order Flow']
        },
        'h4_swing_high': {
            'type': 'float',
            'validity_flag': None,  # Проверяем на None напрямую
            'description': 'H4 Swing High level',
            'required_for': ['VWAP Mean Reversion', 'Range Fade']
        },
        'h4_swing_low': {
            'type': 'float',
            'validity_flag': None,  # Проверяем на None напрямую
            'description': 'H4 Swing Low level',
            'required_for': ['VWAP Mean Reversion', 'Range Fade']
        }
    }
    
    @staticmethod
    def validate_indicators(indicators: Dict, symbol: str = "UNKNOWN") -> Dict[str, List[str]]:
        """
        Проверить качество индикаторов
        
        Args:
            indicators: Словарь с индикаторами
            symbol: Символ для логирования
        
        Returns:
            Dict с результатами:
            {
                'valid': ['indicator_name', ...],
                'invalid': ['indicator_name', ...],
                'warnings': ['warning message', ...]
            }
        """
        result = {
            'valid': [],
            'invalid': [],
            'warnings': []
        }
        
        for indicator_name, config in IndicatorValidator.CRITICAL_INDICATORS.items():
            if indicator_name not in indicators:
                result['invalid'].append(indicator_name)
                result['warnings'].append(
                    f"⚠️  {symbol}: Индикатор '{config['description']}' отсутствует. "
                    f"Нужен для: {', '.join(config['required_for'])}"
                )
                continue
            
            value = indicators[indicator_name]
            validity_flag = config.get('validity_flag')
            
            # Если есть флаг валидности - используем его
            if validity_flag:
                flag_value = indicators.get(validity_flag, None)
                if flag_value == False:
                    result['invalid'].append(indicator_name)
                    result['warnings'].append(
                        f"⚠️  {symbol}: '{config['description']}' имеет fallback данные (API недоступен). "
                        f"Стратегии будут отключены: {', '.join(config['required_for'])}"
                    )
                    continue
            
            # Проверка на None для обязательных индикаторов (swing levels и т.д.)
            if value is None:
                result['invalid'].append(indicator_name)
                result['warnings'].append(
                    f"⚠️  {symbol}: '{config['description']}' = None. "
                    f"Нужен для: {', '.join(config['required_for'])}"
                )
                continue
            
            # Индикатор валиден
            result['valid'].append(indicator_name)
        
        return result
    
    @staticmethod
    def log_validation_results(validation_result: Dict[str, List[str]], symbol: str = "UNKNOWN"):
        """
        Вывести результаты валидации в лог
        
        Args:
            validation_result: Результат от validate_indicators()
            symbol: Символ для логирования
        """
        if validation_result['warnings']:
            for warning in validation_result['warnings']:
                logger.warning(warning)
        
        if validation_result['invalid']:
            logger.warning(
                f"⚠️  {symbol}: {len(validation_result['invalid'])} индикаторов имеют заглушки или отсутствуют: "
                f"{', '.join(validation_result['invalid'])}"
            )
        
        if validation_result['valid']:
            logger.debug(
                f"✅ {symbol}: {len(validation_result['valid'])} индикаторов валидны: "
                f"{', '.join(validation_result['valid'])}"
            )
    
    @staticmethod
    def should_disable_strategy(strategy_name: str, validation_result: Dict[str, List[str]]) -> bool:
        """
        Определить нужно ли отключить стратегию из-за отсутствия индикаторов
        
        Args:
            strategy_name: Название стратегии
            validation_result: Результат от validate_indicators()
        
        Returns:
            True если стратегию нужно отключить
        """
        # Проверяем какие индикаторы нужны для этой стратегии
        required_indicators = []
        
        for indicator_name, config in IndicatorValidator.CRITICAL_INDICATORS.items():
            if strategy_name in config['required_for']:
                required_indicators.append(indicator_name)
        
        # Если хоть один нужный индикатор невалиден - отключаем стратегию
        for indicator in required_indicators:
            if indicator in validation_result['invalid']:
                logger.warning(
                    f"⚠️  Стратегия '{strategy_name}' отключена: "
                    f"отсутствует критичный индикатор '{indicator}'"
                )
                return True
        
        return False
    
    @staticmethod
    def get_startup_validation_summary(indicators: Dict) -> str:
        """
        Получить краткую сводку валидации для вывода при старте
        
        Args:
            indicators: Словарь с индикаторами
        
        Returns:
            Строка с результатами валидации
        """
        validation = IndicatorValidator.validate_indicators(indicators, symbol="STARTUP")
        
        total = len(IndicatorValidator.CRITICAL_INDICATORS)
        valid = len(validation['valid'])
        invalid = len(validation['invalid'])
        
        status_emoji = "✅" if invalid == 0 else "⚠️"
        
        summary = f"{status_emoji} Индикаторы: {valid}/{total} валидны"
        
        if invalid > 0:
            summary += f", {invalid} заглушек: {', '.join(validation['invalid'])}"
        
        return summary
