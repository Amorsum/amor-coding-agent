from enum import StrEnum


class PlanningStrategy(StrEnum):
    DIRECT = "direct"
    STRUCTURED = "structured"


SUPPORTED_PLANNING_STRATEGIES = tuple(strategy.value for strategy in PlanningStrategy)
