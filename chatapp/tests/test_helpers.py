"""Unit tests for helper functions."""

import pytest
from app.helpers.settings import (
    hex_to_rgb,
    generate_color_palette,
    COLOR_PRESETS,
    DEFAULT_PRIMARY_COLOR,
)


class TestHexToRgb:
    """Tests for hex_to_rgb function."""

    def test_converts_hex_to_rgb(self):
        """Test basic hex to RGB conversion."""
        result = hex_to_rgb("#ff0000")
        assert result == "255, 0, 0"

    def test_handles_lowercase_hex(self):
        """Test conversion with lowercase hex."""
        result = hex_to_rgb("#00ff00")
        assert result == "0, 255, 0"

    def test_handles_mixed_case(self):
        """Test conversion with mixed case hex."""
        result = hex_to_rgb("#0000FF")
        assert result == "0, 0, 255"

    def test_handles_without_hash(self):
        """Test conversion without leading hash."""
        result = hex_to_rgb("ffffff")
        assert result == "255, 255, 255"

    def test_default_primary_color(self):
        """Test conversion of default primary color."""
        result = hex_to_rgb(DEFAULT_PRIMARY_COLOR)
        # #7c3aed -> 124, 58, 237
        assert result == "124, 58, 237"


class TestGenerateColorPalette:
    """Tests for generate_color_palette function."""

    def test_generates_all_shades(self):
        """Test that palette includes all expected shades."""
        palette = generate_color_palette("#3b82f6")
        
        expected_shades = ["50", "100", "200", "300", "400", "500", "600", "700", "800", "900"]
        for shade in expected_shades:
            assert shade in palette

    def test_base_color_is_600(self):
        """Test that input color is used as 600 shade."""
        palette = generate_color_palette("#3b82f6")
        
        assert palette["600"] == "#3b82f6"

    def test_lighter_shades_are_lighter(self):
        """Test that lower shade numbers are lighter (higher RGB values)."""
        palette = generate_color_palette("#808080")  # Mid-gray
        
        # 50 should be lighter than 600
        shade_50 = palette["50"].lstrip("#")
        shade_600 = palette["600"].lstrip("#")
        
        r_50 = int(shade_50[0:2], 16)
        r_600 = int(shade_600[0:2], 16)
        
        assert r_50 > r_600

    def test_darker_shades_are_darker(self):
        """Test that higher shade numbers are darker (lower RGB values)."""
        palette = generate_color_palette("#808080")  # Mid-gray
        
        # 900 should be darker than 600
        shade_900 = palette["900"].lstrip("#")
        shade_600 = palette["600"].lstrip("#")
        
        r_900 = int(shade_900[0:2], 16)
        r_600 = int(shade_600[0:2], 16)
        
        assert r_900 < r_600

    def test_output_format_is_valid_hex(self):
        """Test that all palette values are valid hex colors."""
        palette = generate_color_palette("#ff5500")
        
        for shade, color in palette.items():
            assert color.startswith("#")
            assert len(color) == 7
            # Should be valid hex
            int(color[1:], 16)


class TestColorPresets:
    """Tests for COLOR_PRESETS constant."""

    def test_presets_have_required_keys(self):
        """Test that all presets have primary, secondary, and name."""
        for preset_id, preset in COLOR_PRESETS.items():
            assert "primary" in preset, f"Preset {preset_id} missing 'primary'"
            assert "secondary" in preset, f"Preset {preset_id} missing 'secondary'"
            assert "name" in preset, f"Preset {preset_id} missing 'name'"

    def test_preset_colors_are_valid_hex(self):
        """Test that all preset colors are valid hex format."""
        for preset_id, preset in COLOR_PRESETS.items():
            for key in ["primary", "secondary"]:
                color = preset[key]
                assert color.startswith("#"), f"Preset {preset_id}.{key} should start with #"
                assert len(color) == 7, f"Preset {preset_id}.{key} should be 7 chars"
