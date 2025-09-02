# -*- coding: utf-8 -*-
"""
Speed level descriptions for the mech based on donation amounts
Each $10 = 1 level, up to level 101 at $1010+
Now combined with evolution system for visual appearance
"""

import json
import os
from pathlib import Path

# Load translations
def load_speed_translations():
    """Load speed translations from JSON file."""
    try:
        translations_file = Path(__file__).parent / "speed_translations.json"
        with open(translations_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Could not load speed translations: {e}")
        return None

SPEED_TRANSLATIONS = load_speed_translations()

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

def get_speed_info(donation_amount: float) -> tuple:
    """
    Get speed description and color based on donation amount.
    Now uses mech evolution level for proper scaling.
    
    Args:
        donation_amount: Amount in dollars
        
    Returns:
        Tuple of (description, color_hex)
    """
    if donation_amount <= 0:
        return SPEED_DESCRIPTIONS[0]
    
    # Import here to avoid circular imports
    from services.mech.mech_evolutions import get_evolution_level, EVOLUTION_THRESHOLDS
    
    # Get current mech evolution level
    mech_level = get_evolution_level(donation_amount)
    
    # SPECIAL CASE: Level 11 (OMEGA MECH) can reach Glvl 101!
    if mech_level == 11:
        # Level 11 has no next level, so we calculate based on a theoretical max
        theoretical_max = 20000  # Double the requirement
        current_threshold = EVOLUTION_THRESHOLDS[11]  # 10000
        Power_in_level = donation_amount - current_threshold
        max_Power_for_level = theoretical_max - current_threshold  # 10000
        
        if Power_in_level >= max_Power_for_level:
            # TRANSCENDENT MODE!
            return SPEED_DESCRIPTIONS[101]
        elif Power_in_level == 0:
            level = 1
        else:
            level = int((Power_in_level / max_Power_for_level) * 100)
            level = min(max(1, level), 100)
    # For levels 1-4: Direct 1:1 mapping (1$ = 1 Glvl)
    elif mech_level <= 4:
        # Cap at 100 for these levels
        level = min(int(donation_amount), 100)
    else:
        # For levels 5-10: Dynamic distribution across 100 levels
        # Calculate the Power range for current level
        current_threshold = EVOLUTION_THRESHOLDS[mech_level]
        next_threshold = EVOLUTION_THRESHOLDS.get(mech_level + 1, current_threshold * 2)
        
        # Calculate Power within current level range
        Power_in_level = donation_amount - current_threshold
        max_Power_for_level = next_threshold - current_threshold
        
        # Calculate Glvl as percentage of max Power for this level
        if max_Power_for_level > 0:
            # If at exact threshold, start at 1
            if Power_in_level == 0:
                level = 1
            else:
                level = int((Power_in_level / max_Power_for_level) * 100)
                level = min(max(1, level), 100)  # Ensure between 1-100
        else:
            level = 100  # Max level reached
    
    return SPEED_DESCRIPTIONS.get(level, SPEED_DESCRIPTIONS[0])

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
        except Exception as e:
            print(f"Error getting translation for level {level}, language {language}: {e}")
    
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
            from utils.config_manager import get_config_manager
            config_manager = get_config_manager()
            config = config_manager.get_config()
            language = config.get('language', 'en').lower()
            if language not in ['en', 'de', 'fr']:
                language = 'en'
        except:
            language = 'en'
    
    # Get speed info based on POWER amount
    speed_description, speed_color = get_speed_info(Power_amount)
    
    # Calculate speed level with new logic
    from services.mech.mech_evolutions import get_evolution_level, EVOLUTION_THRESHOLDS
    mech_level = get_evolution_level(Power_amount)
    
    if Power_amount <= 0:
        speed_level = 0
    elif mech_level == 11:
        # SPECIAL CASE: Level 11 can reach Glvl 101!
        theoretical_max = 20000
        current_threshold = EVOLUTION_THRESHOLDS[11]
        Power_in_level = Power_amount - current_threshold
        max_Power_for_level = theoretical_max - current_threshold
        
        if Power_in_level >= max_Power_for_level:
            speed_level = 101  # TRANSCENDENT!
        elif Power_in_level == 0:
            speed_level = 1
        else:
            speed_level = int((Power_in_level / max_Power_for_level) * 100)
            speed_level = min(max(1, speed_level), 100)
    elif mech_level <= 4:
        # For levels 1-4: Direct 1:1 mapping
        speed_level = min(int(Power_amount), 100)
    else:
        # For levels 5-10: Dynamic distribution
        current_threshold = EVOLUTION_THRESHOLDS[mech_level]
        next_threshold = EVOLUTION_THRESHOLDS.get(mech_level + 1, current_threshold * 2)
        Power_in_level = Power_amount - current_threshold
        max_Power_for_level = next_threshold - current_threshold
        
        if max_Power_for_level > 0:
            # If at exact threshold, start at 1
            if Power_in_level == 0:
                speed_level = 1
            else:
                speed_level = int((Power_in_level / max_Power_for_level) * 100)
                speed_level = min(max(1, speed_level), 100)
        else:
            speed_level = 100
    
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