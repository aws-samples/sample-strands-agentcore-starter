"""Unit tests for cost calculator module."""

import pytest
from app.admin.cost_calculator import (
    CostCalculator,
    MODEL_PRICING,
    DEFAULT_PRICING,
)


class TestCostCalculator:
    """Tests for CostCalculator class."""

    def test_calculate_cost_known_model(self):
        """Test cost calculation for a known model."""
        calc = CostCalculator()
        
        # 1M input tokens, 500K output tokens with Claude Haiku
        cost = calc.calculate_cost(
            input_tokens=1_000_000,
            output_tokens=500_000,
            model_id="global.anthropic.claude-haiku-4-5-20251001-v1:0",
        )
        
        # Expected: (1M / 1M * $1.00) + (500K / 1M * $5.00) = $1.00 + $2.50 = $3.50
        assert cost == pytest.approx(3.50)

    def test_calculate_cost_unknown_model_returns_zero(self):
        """Test that unknown models return zero cost."""
        calc = CostCalculator()
        
        cost = calc.calculate_cost(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            model_id="unknown-model-id",
        )
        
        assert cost == 0.0

    def test_calculate_cost_zero_tokens(self):
        """Test cost calculation with zero tokens."""
        calc = CostCalculator()
        
        cost = calc.calculate_cost(
            input_tokens=0,
            output_tokens=0,
            model_id="global.anthropic.claude-sonnet-4-5-20250929-v1:0",
        )
        
        assert cost == 0.0

    def test_calculate_cost_custom_pricing(self):
        """Test cost calculation with custom pricing."""
        custom_pricing = {
            "custom-model": {"input": 2.0, "output": 4.0}
        }
        calc = CostCalculator(pricing=custom_pricing)
        
        cost = calc.calculate_cost(
            input_tokens=500_000,
            output_tokens=250_000,
            model_id="custom-model",
        )
        
        # Expected: (500K / 1M * $2.00) + (250K / 1M * $4.00) = $1.00 + $1.00 = $2.00
        assert cost == pytest.approx(2.0)

    def test_calculate_monthly_projection(self):
        """Test monthly cost projection calculation."""
        calc = CostCalculator()
        
        # $100 over 10 days -> $10/day -> $200/month (20 business days)
        projection = calc.calculate_monthly_projection(
            total_cost=100.0,
            days_in_period=10,
        )
        
        assert projection == pytest.approx(200.0)

    def test_calculate_monthly_projection_zero_days(self):
        """Test monthly projection with zero days returns zero."""
        calc = CostCalculator()
        
        projection = calc.calculate_monthly_projection(
            total_cost=100.0,
            days_in_period=0,
        )
        
        assert projection == 0.0

    def test_get_model_rates_known_model(self):
        """Test getting rates for a known model."""
        calc = CostCalculator()
        
        rates = calc.get_model_rates("us.amazon.nova-pro-v1:0")
        
        assert rates["input"] == 0.80
        assert rates["output"] == 3.20

    def test_get_model_rates_unknown_model(self):
        """Test getting rates for unknown model returns defaults."""
        calc = CostCalculator()
        
        rates = calc.get_model_rates("unknown-model")
        
        assert rates == DEFAULT_PRICING
