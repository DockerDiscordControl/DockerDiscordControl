# -*- coding: utf-8 -*-
"""
Mech Evolution System - Maps donation amounts to evolution levels
"""

# Evolution thresholds in dollars - progressive pattern
EVOLUTION_THRESHOLDS = {
    0: 0,      # SCRAP MECH - $0
    1: 20,     # REPAIRED MECH - $20
    2: 50,     # STANDARD MECH - $50
    3: 100,    # ENHANCED MECH - $100
    4: 200,    # ADVANCED MECH - $200
    5: 400,    # ELITE MECH - $400
    6: 800,    # CYBER MECH - $800
    7: 1500,   # PLASMA MECH - $1500
    8: 2500,   # QUANTUM MECH - $2500
    9: 4000,   # DIVINE MECH - $4000
}

EVOLUTION_NAMES = {
    0: "SCRAP MECH",
    1: "REPAIRED MECH", 
    2: "STANDARD MECH",
    3: "ENHANCED MECH",
    4: "ADVANCED MECH",
    5: "ELITE MECH",
    6: "CYBER MECH",
    7: "PLASMA MECH", 
    8: "QUANTUM MECH",
    9: "DIVINE MECH",
}

EVOLUTION_DESCRIPTIONS = {
    0: "Barely holding together with rust and spare parts",
    1: "Basic repairs complete, systems barely functional",
    2: "Standard military-grade combat chassis",
    3: "Reinforced armor plating and enhanced servos",
    4: "Advanced targeting systems and weapon upgrades",
    5: "Elite combat protocols and titanium armor",
    6: "Cybernetic neural interface and energy shields",
    7: "Plasma-powered core with quantum processors",
    8: "Quantum entanglement drive and phase shifting",
    9: "Transcendent technology beyond mortal comprehension",
}

EVOLUTION_COLORS = {
    0: "#444444",  # Dark gray
    1: "#666666",  # Light gray
    2: "#888888",  # Steel
    3: "#0099cc",  # Blue
    4: "#00ccff",  # Cyan
    5: "#ffcc00",  # Gold
    6: "#ff6600",  # Orange
    7: "#cc00ff",  # Purple
    8: "#00ffff",  # Quantum cyan
    9: "#ffff00",  # Divine gold
}

def get_evolution_level(total_donations: float) -> int:
    """
    Calculate evolution level based on total donations.
    
    Args:
        total_donations: Total donation amount in dollars/euros
        
    Returns:
        Evolution level (0-9)
    """
    if total_donations <= 0:
        return 0
    
    # Find the highest evolution level the donations qualify for
    for level in range(9, -1, -1):  # Check from highest to lowest
        if total_donations >= EVOLUTION_THRESHOLDS[level]:
            return level
    
    return 0

def get_evolution_info(total_donations: float) -> dict:
    """
    Get complete evolution information for given donation amount.
    
    Args:
        total_donations: Total donation amount in dollars/euros
        
    Returns:
        Dictionary with level, name, color, next_threshold, descriptions
    """
    level = get_evolution_level(total_donations)
    name = EVOLUTION_NAMES[level]
    color = EVOLUTION_COLORS[level]
    description = EVOLUTION_DESCRIPTIONS[level]
    
    # Calculate next evolution threshold and sneak peek
    next_threshold = None
    next_name = None
    next_description = None
    amount_needed = None
    
    if level < 9:
        next_threshold = EVOLUTION_THRESHOLDS[level + 1]
        next_name = EVOLUTION_NAMES[level + 1]
        next_description = EVOLUTION_DESCRIPTIONS[level + 1]
        amount_needed = next_threshold - total_donations
    
    return {
        'level': level,
        'name': name, 
        'color': color,
        'description': description,
        'current_threshold': EVOLUTION_THRESHOLDS[level],
        'next_threshold': next_threshold,
        'next_name': next_name,
        'next_description': next_description,
        'amount_needed': amount_needed,
        'progress_to_next': None if next_threshold is None else min(100, (total_donations - EVOLUTION_THRESHOLDS[level]) / (next_threshold - EVOLUTION_THRESHOLDS[level]) * 100)
    }

def get_mech_filename(evolution_level: int) -> str:
    """
    Get filename for mech evolution spritesheet.
    
    Args:
        evolution_level: Evolution level (0-9)
        
    Returns:
        Filename for the spritesheet
    """
    return f"mech_level_{evolution_level}.png"