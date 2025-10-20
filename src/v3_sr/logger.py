"""
V3 S/R Strategy Logger

Console logging for V3 S/R strategy operations.
"""

import logging
import sys


# Create custom logger for V3 S/R strategy
v3_sr_logger = logging.getLogger('v3_sr_strategy')
v3_sr_logger.setLevel(logging.INFO)

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)

# Format
formatter = logging.Formatter(
    '%(asctime)s | %(levelname)-8s | V3_SR | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S %Z'
)
console_handler.setFormatter(formatter)

# Add handler
if not v3_sr_logger.handlers:
    v3_sr_logger.addHandler(console_handler)

# Prevent propagation to root logger
v3_sr_logger.propagate = False
