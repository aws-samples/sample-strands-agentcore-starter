"""Cost calculator for usage analytics.

This module provides the CostCalculator class for calculating costs
based on token usage and model pricing rates.
"""

from typing import Dict

from app.helpers.model_catalog import get_pricing


# Model pricing in USD per 1 million tokens, sourced from the single
# source of truth at app/static/models.json (shared with the front-end).
# Format: {"model_id": {"input": rate, "output": rate}}
MODEL_PRICING: Dict[str, Dict[str, float]] = get_pricing()

# Default pricing for unknown models
DEFAULT_PRICING = {"input": 0.00, "output": 0.00}


class CostCalculator:
    """Calculate costs based on token usage and model pricing.
    
    This class provides methods to calculate costs for token usage
    and project monthly costs based on usage patterns.
    """
    
    def __init__(self, pricing: Dict[str, Dict[str, float]] = None):
        """Initialize the cost calculator.
        
        Args:
            pricing: Optional custom pricing dictionary. Defaults to MODEL_PRICING.
        """
        self.pricing = pricing or MODEL_PRICING
    
    def calculate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        model_id: str,
    ) -> float:
        """Calculate cost in USD for given token usage.
        
        Uses the formula: (input_tokens / 1,000,000 * input_rate) + 
                         (output_tokens / 1,000,000 * output_rate)
        
        Args:
            input_tokens: Number of input/prompt tokens
            output_tokens: Number of output/response tokens
            model_id: The model identifier for pricing lookup
            
        Returns:
            Cost in USD
        """
        rates = self.pricing.get(model_id, DEFAULT_PRICING)
        
        input_cost = (input_tokens / 1_000_000) * rates["input"]
        output_cost = (output_tokens / 1_000_000) * rates["output"]
        
        return input_cost + output_cost
    
    def calculate_monthly_projection(
        self,
        total_cost: float,
        days_in_period: int,
    ) -> float:
        """Project monthly cost based on average daily usage.
        
        Uses the formula: (total_cost / days_in_period) * 20
        
        Args:
            total_cost: Total cost for the period in USD
            days_in_period: Number of days in the measurement period
            
        Returns:
            Projected monthly cost in USD
        """
        if days_in_period <= 0:
            return 0.0
        
        daily_average = total_cost / days_in_period
        return daily_average * 20
    
    def get_model_rates(self, model_id: str) -> Dict[str, float]:
        """Get pricing rates for a specific model.
        
        Args:
            model_id: The model identifier
            
        Returns:
            Dictionary with 'input' and 'output' rates per 1M tokens
        """
        return self.pricing.get(model_id, DEFAULT_PRICING)
