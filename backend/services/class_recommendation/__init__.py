"""Pair-level embedding class recommendation for SmartMQTT."""

from .application import (
    ClassRecommendationApplication,
    build_class_recommendation_application,
)
from .domain import *

__all__ = ["ClassRecommendationApplication", "build_class_recommendation_application"]
