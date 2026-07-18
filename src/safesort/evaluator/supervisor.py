"""Evaluator-side observer; application events flow into this package only."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from safesort.contracts.events import Classification, DecisionEvent, ExecutionStatus


@dataclass(frozen=True, slots=True)
class ScoredDecision:
    event: DecisionEvent
    expected_classification: Classification

    @property
    def classification_correct(self) -> bool:
        return self.event.classification is self.expected_classification

    @property
    def successful(self) -> bool:
        return self.event.execution_status is ExecutionStatus.SUCCESS


class EvaluationObserver:
    """Correlates runtime-assigned item_seq after receiving a committed event."""

    @staticmethod
    def score(payload: Mapping[str, Any], expected_classification: Classification) -> ScoredDecision:
        event = DecisionEvent.from_mapping(payload)
        return ScoredDecision(event=event, expected_classification=expected_classification)
