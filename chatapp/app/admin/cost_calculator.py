"""Cost calculator for usage analytics.

This module provides the CostCalculator class for calculating costs
based on token usage and model pricing rates.
"""

from typing import Dict

from app.helpers.model_catalog import get_pricing


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
            pricing: Optional custom pricing dictionary. Defaults to live catalog pricing.
        """
        self.pricing = pricing if pricing is not None else get_pricing()

    def _resolve_rates(self, model_id: str) -> Dict[str, float]:
        """Resolve pricing rates for a model id.

        Handles both the short catalog ids used by the model selector
        (e.g. ``anthropic.claude-haiku-4-5``) and fully-qualified Bedrock
        model ids (e.g. ``global.anthropic.claude-haiku-4-5-20251001-v1:0``),
        which embed a region prefix and version suffix. When there's no exact
        match, the longest catalog id that appears within the given model id
        wins, so a fully-qualified id still maps to the right pricing instead
        of silently costing $0.

        Args:
            model_id: The model identifier to price

        Returns:
            The pricing dict for the model, or DEFAULT_PRICING if unknown.
        """
        if not model_id:
            return DEFAULT_PRICING
        # Exact match (the common case for catalog ids)
        rates = self.pricing.get(model_id)
        if rates is not None:
            return rates
        # Fall back to the longest catalog id contained in the model id
        best_key = None
        for key in self.pricing:
            if key and key in model_id and (best_key is None or len(key) > len(best_key)):
                best_key = key
        if best_key is not None:
            return self.pricing[best_key]
        return DEFAULT_PRICING

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
        rates = self._resolve_rates(model_id)
        
        input_cost = (input_tokens / 1_000_000) * rates["input"]
        output_cost = (output_tokens / 1_000_000) * rates["output"]
        
        return input_cost + output_cost
    
    def calculate_monthly_projection(
        self,
        total_cost: float,
        days_in_period: int,
    ) -> float:
        """Project monthly cost based on average daily usage.
        
        Uses the formula: (total_cost / days_in_period) * 30

        Args:
            total_cost: Total cost for the period in USD
            days_in_period: Number of days in the measurement period

        Returns:
            Projected monthly cost in USD
        """
        if days_in_period <= 0:
            return 0.0

        daily_average = total_cost / days_in_period
        return daily_average * 30
    
    def get_model_rates(self, model_id: str) -> Dict[str, float]:
        """Get pricing rates for a specific model.
        
        Args:
            model_id: The model identifier
            
        Returns:
            Dictionary with 'input' and 'output' rates per 1M tokens
        """
        return self._resolve_rates(model_id)
