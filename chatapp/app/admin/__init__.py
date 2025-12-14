"""Admin module for usage analytics dashboard.

This module provides the admin functionality for viewing and analyzing
usage metrics from agent invocations. It includes:

- UsageRepository: Query and aggregate usage data from DynamoDB
- CostCalculator: Calculate costs based on token usage and model pricing

Routes are defined in app/routes/admin.py and templates in app/templates/admin/.
"""

from app.admin.repository import UsageRepository
from app.admin.cost_calculator import CostCalculator

__all__ = ["UsageRepository", "CostCalculator"]
