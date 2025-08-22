# -*- coding: utf-8 -*-
"""
Mech Evolution System - Maps donation amounts to evolution levels
"""

# Evolution thresholds in dollars - progressive pattern
EVOLUTION_THRESHOLDS = {
    1: 0,      # SCRAP MECH - $0 (Level 1 starting point)
    2: 20,     # REPAIRED MECH - $20
    3: 50,     # STANDARD MECH - $50
    4: 100,    # ENHANCED MECH - $100
    5: 200,    # ADVANCED MECH - $200
    6: 400,    # ELITE MECH - $400
    7: 800,    # CYBER MECH - $800
    8: 1500,   # PLASMA MECH - $1500
    9: 2500,   # QUANTUM MECH - $2500
    10: 4000,  # DIVINE MECH - $4000
    11: 10000, # OMEGA MECH - $10000 (Secret Ultra Level!)
}

EVOLUTION_NAMES = {
    1: "SCRAP MECH",
    2: "REPAIRED MECH", 
    3: "STANDARD MECH",
    4: "ENHANCED MECH",
    5: "ADVANCED MECH",
    6: "ELITE MECH",
    7: "CYBER MECH",
    8: "PLASMA MECH", 
    9: "QUANTUM MECH",
    10: "DIVINE MECH",
    11: "OMEGA MECH",  # The legendary final form!
}

EVOLUTION_DESCRIPTIONS = {
    1: "Barely holding together with rust and spare parts",
    2: "Basic repairs complete, systems barely functional",
    3: "Standard military-grade combat chassis",
    4: "Reinforced armor plating and enhanced servos",
    5: "Advanced targeting systems and weapon upgrades",
    6: "Elite combat protocols and titanium armor",
    7: "Cybernetic neural interface and energy shields",
    8: "Plasma-powered core with quantum processors",
    9: "Quantum entanglement drive and phase shifting",
    10: "Transcendent technology beyond mortal comprehension",
    11: "Reality-bending omnipotent war machine of the gods",
}

EVOLUTION_COLORS = {
    1: "#444444",  # Dark gray
    2: "#666666",  # Light gray
    3: "#888888",  # Steel
    4: "#0099cc",  # Blue
    5: "#00ccff",  # Cyan
    6: "#ffcc00",  # Gold
    7: "#ff6600",  # Orange
    8: "#cc00ff",  # Purple
    9: "#00ffff",  # Quantum cyan
    10: "#ffff00", # Divine gold
    11: "#ff00ff", # Omega magenta - Reality itself bends
}

def get_evolution_level(total_donations: float) -> int:
    """
    Calculate evolution level based on total donations.
    
    Args:
        total_donations: Total donation amount in dollars/euros
        
    Returns:
        Evolution level (1-11)
    """
    if total_donations < 0:
        return 1  # Minimum is level 1 now
    
    # Find the highest evolution level the donations qualify for
    for level in range(11, 0, -1):  # Check from highest (11) to lowest (1)
        if level in EVOLUTION_THRESHOLDS and total_donations >= EVOLUTION_THRESHOLDS[level]:
            return level
    
    return 1  # Default to level 1 (SCRAP MECH)

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
    
    if level < 11:  # Now goes up to 11
        next_threshold = EVOLUTION_THRESHOLDS.get(level + 1)
        if next_threshold is not None:
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
        evolution_level: Evolution level (1-11)
        
    Returns:
        Filename for the spritesheet
    """
    return f"mech_level_{evolution_level}.png"