from __future__ import annotations

from typing import Dict

from strategies.base import Strategy
from strategies.example_strategy import ExampleStrategy


class StrategyRegistry:
    def __init__(self):
        self.strategies: Dict[str, Strategy] = {}

    def get_active_strategy(self, symbol: str) -> Strategy:
        if symbol not in self.strategies:
            self.strategies[symbol] = ExampleStrategy()
        return self.strategies[symbol]
