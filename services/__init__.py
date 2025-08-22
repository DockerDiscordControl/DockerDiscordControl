# -*- coding: utf-8 -*-
"""
Services Package - Centralized business logic services

This package contains the core business logic services that provide
clean APIs for mech animations, donations, and other DDC features.
"""

import sys
import os

# Add the parent directory to Python path to ensure proper imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)