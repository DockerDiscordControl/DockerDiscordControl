# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Speed level descriptions for the mech based on donation amounts
Each $10 = 1 level, up to level 101 at $1010+
Now combined with evolution system for visual appearance
"""

import json
import os
from pathlib import Path

# Load speed translations from JSON
try:
    # Robust absolute path relative to project root
    translations_path = Path(__file__).parents[2] / "config" / "mech" / "speed_translations.json"
    if translations_path.exists():
        with open(translations_path, "r", encoding="utf-8") as f:
            SPEED_TRANSLATIONS = json.load(f)
    else:
        # Fallback to empty if file missing
        SPEED_TRANSLATIONS = {}
except Exception:
    # Silent fallback - logging not available at module load time
    SPEED_TRANSLATIONS = {}

SPEED_DESCRIPTIONS = {
    0: ("OFFLINE", "#888888"),
    1: ("Motionless", "#4a4a4a"),
    2: ("Barely perceptible", "#525252"),
    3: ("Extremely sluggish", "#5a5a5a"),
    4: ("Painfully hesitant", "#626262"),
    5: ("Excruciatingly lethargic", "#6a6a6a"),
    6: ("Ultra-slow", "#727272"),
    7: ("Almost crawling", "#7a7a7a"),
    8: ("Truly crawling", "#828282"),
    9: ("Snail-paced", "#8a8a8a"),
    10: ("Glacially slow", "#929292"),
    11: ("Heavy-footed", "#9a9a9a"),
    12: ("Weary plodding", "#a2a2a2"),
    13: ("Drearily trudging", "#aaaaaa"),
    14: ("Stumbling forward", "#b2b2b2"),
    15: ("Faltering pace", "#bababa"),
    16: ("Limping along", "#c2c2c2"),
    17: ("Dragging feet", "#cacaca"),
    18: ("Reluctant stride", "#d2d2d2"),
    19: ("Sluggish shuffling", "#dadada"),
    20: ("Slow but continuous", "#e2e2e2"),
    21: ("Leisurely relaxed", "#cc6600"),
    22: ("Casual and easy", "#cc7700"),
    23: ("Moderately steady", "#cc8800"),
    24: ("Comfortable stride", "#cc9900"),
    25: ("Measured walking", "#ccaa00"),
    26: ("Balanced and even", "#ccbb00"),
    27: ("Mildly brisk", "#bbcc00"),
    28: ("Purposeful steady", "#aacc00"),
    29: ("Clearly brisker", "#99cc00"),
    30: ("Decisive stride", "#88cc00"),
    31: ("Quickened step", "#77cc00"),
    32: ("Energetic pace", "#66cc00"),
    33: ("Noticeably brisk", "#55cc00"),
    34: ("Sharply focused", "#44cc00"),
    35: ("Fast stride", "#33cc00"),
    36: ("Strong and firm", "#22cc00"),
    37: ("Forcefully brisk", "#11cc00"),
    38: ("Rapid walking", "#00cc00"),
    39: ("Swift step", "#00cc11"),
    40: ("Quick-paced", "#00cc22"),
    41: ("Very brisk", "#00cc33"),
    42: ("Clearly fast", "#00cc44"),
    43: ("Forcefully rapid", "#00cc55"),
    44: ("Rushing forward", "#00cc66"),
    45: ("Hurrying intensely", "#00cc77"),
    46: ("Lively fast", "#00cc88"),
    47: ("Speedy motion", "#00cc99"),
    48: ("Snappy fast", "#00ccaa"),
    49: ("Nimble quick", "#00ccbb"),
    50: ("Sharply swift", "#00cccc"),
    51: ("Fast and urgent", "#00bbcc"),
    52: ("Highly accelerated", "#00aacc"),
    53: ("Energetically quick", "#0099cc"),
    54: ("Spirited dash", "#0088cc"),
    55: ("Racing step", "#0077cc"),
    56: ("Storming forward", "#0066cc"),
    57: ("Rapidly urgent", "#0055cc"),
    58: ("Extremely swift", "#0044cc"),
    59: ("Desperately fast", "#0033cc"),
    60: ("Almost running", "#0022cc"),
    61: ("Slow jogging", "#0011cc"),
    62: ("Light jogging", "#0000cc"),
    63: ("Steady jogging", "#1100cc"),
    64: ("Quick jogging", "#2200cc"),
    65: ("Fast jogging", "#3300cc"),
    66: ("Easy running", "#4400cc"),
    67: ("Moderate running", "#5500cc"),
    68: ("Strong running", "#6600cc"),
    69: ("Swift running", "#7700cc"),
    70: ("Rapid running", "#8800cc"),
    71: ("Intense running", "#9900cc"),
    72: ("Very fast running", "#aa00cc"),
    73: ("Furious running", "#bb00cc"),
    74: ("Blazing sprint", "#cc00cc"),
    75: ("Relentless sprint", "#cc00bb"),
    76: ("Explosive sprint", "#cc00aa"),
    77: ("Overpowering sprint", "#cc0099"),
    78: ("Jet-fast sprint", "#cc0088"),
    79: ("Blisteringly fast", "#cc0077"),
    80: ("Supersonic pace", "#cc0066"),
    81: ("Hypersonic burst", "#cc0055"),
    82: ("Blazing meteor-fast", "#cc0044"),
    83: ("Comet-like rushing", "#cc0033"),
    84: ("Blindingly swift", "#cc0022"),
    85: ("Breakneck velocity", "#cc0011"),
    86: ("Rocket-speed", "#cc0000"),
    87: ("Stellar velocity", "#ff0000"),
    88: ("Asteroid-surge", "#ff1100"),
    89: ("Planet-crossing speed", "#ff2200"),
    90: ("Star-chasing speed", "#ff3300"),
    91: ("Relativistic rush", "#ff4400"),
    92: ("Near-photonic speed", "#ff5500"),
    93: ("Photon-paced", "#ff6600"),
    94: ("Warp-level 1", "#ff7700"),
    95: ("Warp-level 5", "#ff8800"),
    96: ("Warp-level 9", "#ff9900"),
    97: ("Transwarp surge", "#ffaa00"),
    98: ("Nearly lightspeed", "#ffbb00"),
    99: ("True lightspeed", "#ffcc00"),
    100: ("Beyond-lightspeed", "#ffdd00"),
    101: ("REALITY-BENDING OMNISPEED", "#ff00ff")  # OMEGA MECH at full power - THE ULTIMATE ACHIEVEMENT!
}

def _get_evolution_context(donation_amount: float) -> tuple:
    """
    HELPER: Get evolution level and max power for a donation amount.

    Single source of truth for evolution context retrieval.

    Args:
        donation_amount: Amount in dollars

    Returns:
        Tuple of (evolution_level, max_power_for_level)

        max_power_for_level is the threshold to reach the NEXT level,
        which is the correct range for speed calculations within the current level.

    Raises:
        ImportError: If mech_evolutions module is not available
    """
    from services.mech.mech_evolutions import get_evolution_level, get_evolution_level_info

    evolution_level = get_evolution_level(donation_amount)
    evolution_level_info = get_evolution_level_info(evolution_level)

    if not evolution_level_info:
        raise ValueError(f"Unknown evolution level: {evolution_level}")

    # Get next level threshold for correct speed scaling
    # Example: Level 6 (threshold=30) should use Level 7's threshold (35) as max_power
    # so that power 30-34.99 scales correctly from 0-100% speed within Level 6
    next_level_info = get_evolution_level_info(evolution_level + 1)

    if next_level_info:
        # Use next level's threshold as max power for this level
        max_power = next_level_info.base_cost
    else:
        # Max level (11): Use current level's power_max
        max_power = evolution_level_info.power_max

    return evolution_level, max_power


def _calculate_power_ratio(power_amount: float, max_power: float) -> float:
    """
    HELPER: Calculate power ratio capped at 1.0.

    Single source of truth for power ratio calculation.

    Args:
        power_amount: Current power amount
        max_power: Maximum power for level

    Returns:
        Power ratio between 0.0 and 1.0
    """
    return min(1.0, power_amount / max_power)


def _calculate_speed_level_from_power_ratio(current_level: int, power_amount: float, max_power_for_level: float) -> int:
    """
    HELPER: Calculate speed level based on power ratio within current evolution level.

    This consolidates the speed calculation logic used in multiple places.
    """
    # Calculate speed level based on power ratio within current evolution level
    power_ratio = _calculate_power_ratio(power_amount, max_power_for_level)

    # SPECIAL CASE: Level 11 (OMEGA MECH) can reach speed level 101!
    if current_level == 11 and power_ratio >= 1.0:
        # Check if we're at transcendent level (double the requirement)
        transcendent_threshold = max_power_for_level * 2  # 20000 for level 11
        if power_amount >= transcendent_threshold:
            return 101  # TRANSCENDENT!
        else:
            return 100
    elif power_amount <= 0:
        return 0
    else:
        # Scale from 1-100 based on power ratio (never 0 if we have any power)
        return max(1, min(100, int(power_ratio * 100)))

def get_speed_info(donation_amount: float) -> tuple:
    """
    Get speed description and color based on donation amount.
    Uses MechDataStore for centralized data access.

    Args:
        donation_amount: Amount in dollars (current power)

    Returns:
        Tuple of (description, color_hex)
    """
    if donation_amount <= 0:
        return SPEED_DESCRIPTIONS[0]

    try:
        # Get evolution context using helper (DRY)
        evolution_level, max_power_for_level = _get_evolution_context(donation_amount)

        # Calculate speed level using consolidated logic
        level = _calculate_speed_level_from_power_ratio(evolution_level, donation_amount, max_power_for_level)
        return SPEED_DESCRIPTIONS.get(level, SPEED_DESCRIPTIONS[0])

    except (ImportError, AttributeError) as e:
        # Service dependency errors (mech_evolutions not available)
        print(f"Service dependency error in get_speed_info: {e}")
        return SPEED_DESCRIPTIONS[1]
    except (ValueError, TypeError, KeyError, ZeroDivisionError) as e:
        # Calculation/data access errors (evolution level, power ratio)
        print(f"Calculation error in get_speed_info: {e}")
        return SPEED_DESCRIPTIONS[1]

def get_speed_emoji(level: int) -> str:
    """
    Get appropriate emoji for speed level.
    Now returns empty string since mech is the visual indicator.
    """
    return ""  # No emoji needed - mech animation shows speed

def get_translated_speed_description(level: int, language: str = "en") -> str:
    """
    Get translated speed description for a given level.

    Args:
        level: Speed level (0-101)
        language: Language code ('en', 'de', 'fr')

    Returns:
        Translated speed description
    """
    if SPEED_TRANSLATIONS and "speed_descriptions" in SPEED_TRANSLATIONS:
        try:
            level_str = str(level)
            if level_str in SPEED_TRANSLATIONS["speed_descriptions"]:
                translations = SPEED_TRANSLATIONS["speed_descriptions"][level_str]
                if language in translations:
                    return translations[language]
        except (KeyError, ValueError, TypeError) as e:
            # Dictionary access/data errors (missing translations, invalid keys)
            print(f"Data error getting translation for level {level}, language {language}: {e}")

    # Fallback to English from SPEED_DESCRIPTIONS
    return SPEED_DESCRIPTIONS.get(level, SPEED_DESCRIPTIONS[0])[0]

def get_combined_mech_status(Power_amount: float, total_donations_received: float = None, language: str = None) -> dict:
    """
    Get combined evolution and speed status for the mech.

    Args:
        Power_amount: Current Power amount (for speed)
        total_donations_received: Total donations ever received (for evolution).
                                If None, uses Power_amount for backwards compatibility.
        language: Language code ('en', 'de', 'fr'). If None, tries to get from config.

    Returns:
        Dictionary with evolution info, speed info, and combined status
    """
    # If total_donations_received not provided, use Power_amount for backwards compatibility
    if total_donations_received is None:
        total_donations_received = Power_amount

    # Import here to avoid circular imports
    try:
        from services.mech.mech_evolutions import get_evolution_info
        evolution_info = get_evolution_info(total_donations_received)
    except ImportError:
        evolution_info = {
            'level': 0,
            'name': 'SCRAP MECH',
            'color': '#444444',
            'description': 'Barely holding together',
            'current_threshold': 0,
            'next_threshold': 20,
            'next_name': 'REPAIRED MECH',
            'next_description': 'Basic repairs complete',
            'amount_needed': 20
        }

    # Get language from config if not provided
    if language is None:
        try:
            # SERVICE FIRST: Use Request/Result pattern for config access
            from services.config.config_service import get_config_service, GetConfigRequest
            config_manager = get_config_service()
            config_request = GetConfigRequest(force_reload=False)
            config_result = config_manager.get_config_service(config_request)

            if config_result.success:
                language = config_result.config.get('language', 'en').lower()
                if language not in ['en', 'de', 'fr']:
                    language = 'en'
            else:
                language = 'en'
        except (ImportError, AttributeError, RuntimeError, KeyError) as e:
            # Service/config access errors (config service unavailable, get failures)
            print(f"Error accessing config for language: {e}")
            language = 'en'

    # Calculate speed level using helper (DRY)
    # IMPORTANT: Use total_donations_received for evolution level, Power_amount for speed calculation
    try:
        # Get evolution context using total donations (NOT current power!)
        # This ensures we use actual mech level, not power-degraded level
        evolution_level, max_power_for_level = _get_evolution_context(total_donations_received)

        # Calculate speed level using actual evolution level and current power
        speed_level = _calculate_speed_level_from_power_ratio(evolution_level, Power_amount, max_power_for_level)

    except (ImportError, AttributeError) as e:
        # Service dependency errors (mech_evolutions not available)
        print(f"Service dependency error calculating speed level: {e}")
        speed_level = min(int(Power_amount), 100)
    except (ValueError, TypeError, ZeroDivisionError) as e:
        # Calculation errors (power ratio, type conversion)
        print(f"Calculation error calculating speed level: {e}")
        speed_level = min(int(Power_amount), 100)

    # Get speed description and color from SPEED_DESCRIPTIONS using calculated level
    # This ensures consistency between speed_level and speed_description
    if speed_level in SPEED_DESCRIPTIONS:
        speed_description, speed_color = SPEED_DESCRIPTIONS[speed_level]
    else:
        speed_description, speed_color = SPEED_DESCRIPTIONS.get(0, ("OFFLINE", "#888888"))

    # Get translated speed description
    translated_speed_description = get_translated_speed_description(speed_level, language)

    return {
        'evolution': evolution_info,
        'speed': {
            'level': speed_level,
            'description': translated_speed_description,
            'color': speed_color
        },
        'combined_status': f"{evolution_info['name']} - {translated_speed_description}",
        'primary_color': evolution_info['color'],  # Use evolution color as primary
        'Power_amount': Power_amount,
        'total_donations_received': total_donations_received
    }
