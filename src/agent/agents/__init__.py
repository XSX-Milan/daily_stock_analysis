# -*- coding: utf-8 -*-
"""
Specialised agents for the multi-agent pipeline.

Each agent class inherits from :class:`BaseAgent` and implements
a focused analysis scope (technical, intelligence, decision, risk).
"""

from src.agent.agents.base_agent import BaseAgent
from src.agent.agents.technical_agent import TechnicalAgent
from src.agent.agents.intel_agent import IntelAgent
from src.agent.agents.decision_agent import DecisionAgent
from src.agent.agents.risk_agent import RiskAgent
from src.agent.agents.portfolio_agent import PortfolioAgent
from src.agent.agents.recommendation_fundamental_agent import (
    RecommendationFundamentalAgent,
)
from src.agent.agents.recommendation_macro_agent import RecommendationMacroAgent
from src.agent.agents.recommendation_risk_agent import RecommendationRiskAgent
from src.agent.agents.recommendation_sentiment_agent import RecommendationSentimentAgent
from src.agent.agents.recommendation_technical_agent import RecommendationTechnicalAgent

__all__ = [
    "BaseAgent",
    "TechnicalAgent",
    "IntelAgent",
    "DecisionAgent",
    "RiskAgent",
    "PortfolioAgent",
    "RecommendationFundamentalAgent",
    "RecommendationMacroAgent",
    "RecommendationRiskAgent",
    "RecommendationSentimentAgent",
    "RecommendationTechnicalAgent",
]
