# -*- coding: utf-8 -*-
"""Constants used by recommendation scoring and ranking."""

from src.recommendation.models import ScoringWeights

BUY_NOW_MIN_SCORE = 80.0
POSITION_MIN_SCORE = 60.0
WAIT_PULLBACK_MIN_SCORE = 40.0

DEFAULT_TOP_N_PER_SECTOR = 10
DEFAULT_SCORING_WEIGHTS = ScoringWeights()
