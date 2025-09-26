#!/usr/bin/env python3
"""
Dynamischer Loader für verschlüsselte Mech-Evolution Bilder.
Lädt und entschlüsselt die Mech-Animationen basierend auf Level.
"""

import os
import json
import io
from pathlib import Path
from typing import Optional, Dict, Any
from PIL import Image
from cryptography.fernet import Fernet
import logging

logger = logging.getLogger(__name__)

# Encryption Key - sollte sicher aufbewahrt werden
ENCRYPTION_KEY = b'ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg='

class MechEvolutionLoader:
    """Lädt und entschlüsselt Mech-Evolution Animationen."""

    def __init__(self):
        self.base_path = Path('encrypted_assets/mech_evolutions')
        self.config = self._load_config()
        self.cipher = Fernet(ENCRYPTION_KEY)
        self._cache = {}

    def _load_config(self) -> Dict[str, Any]:
        """Lädt die Konfigurations-Datei."""
        config_path = self.base_path / 'mech_config.json'
        if not config_path.exists():
            logger.warning(f"Config file not found: {config_path}")
            return {}

        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return {}

    def get_mech_animation(self, level: int) -> Optional[bytes]:
        """
        Holt die entschlüsselte WebP-Animation für ein bestimmtes Level.

        Args:
            level: Mech-Level (2-10)

        Returns:
            WebP-Animationsdaten als bytes oder None
        """
        # Check cache first
        cache_key = f"level_{level}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Check if level exists in config
        if cache_key not in self.config:
            logger.warning(f"Level {level} not found in config")
            return None

        level_info = self.config[cache_key]
        enc_file = self.base_path / level_info['file']

        if not enc_file.exists():
            logger.error(f"Encrypted file not found: {enc_file}")
            return None

        try:
            # Lese verschlüsselte Datei
            with open(enc_file, 'rb') as f:
                encrypted_data = f.read()

            # Entschlüssele
            decrypted_data = self.cipher.decrypt(encrypted_data)

            # Cache für schnelleren Zugriff
            self._cache[cache_key] = decrypted_data

            return decrypted_data

        except Exception as e:
            logger.error(f"Failed to decrypt mech level {level}: {e}")
            return None

    def get_mech_image(self, level: int, frame: int = 0) -> Optional[Image.Image]:
        """
        Holt ein einzelnes Frame aus der Mech-Animation.

        Args:
            level: Mech-Level (2-10)
            frame: Frame-Nummer (default: 0)

        Returns:
            PIL Image oder None
        """
        webp_data = self.get_mech_animation(level)
        if not webp_data:
            return None

        try:
            # Öffne WebP-Animation
            img = Image.open(io.BytesIO(webp_data))

            # Gehe zum gewünschten Frame
            if hasattr(img, 'n_frames') and img.n_frames > 1:
                frame = min(frame, img.n_frames - 1)
                img.seek(frame)

            # Konvertiere zu RGBA falls nötig
            if img.mode != 'RGBA':
                img = img.convert('RGBA')

            return img.copy()

        except Exception as e:
            logger.error(f"Failed to extract frame {frame} from level {level}: {e}")
            return None

    def get_level_info(self, level: int) -> Optional[Dict[str, Any]]:
        """
        Holt Informationen über ein bestimmtes Level.

        Args:
            level: Mech-Level (2-10)

        Returns:
            Dict mit Level-Informationen oder None
        """
        cache_key = f"level_{level}"
        if cache_key in self.config:
            return self.config[cache_key].copy()
        return None

    def get_available_levels(self) -> list:
        """Gibt Liste der verfügbaren Level zurück."""
        levels = []
        for key in self.config:
            if key.startswith('level_'):
                level_num = self.config[key]['level']
                levels.append(level_num)
        return sorted(levels)

# Globale Instanz
_loader_instance = None

def get_mech_loader() -> MechEvolutionLoader:
    """Gibt die globale MechEvolutionLoader Instanz zurück."""
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = MechEvolutionLoader()
    return _loader_instance

# Convenience Functions
def get_mech_image(level: int, frame: int = 0) -> Optional[Image.Image]:
    """Convenience function zum Abrufen eines Mech-Bildes."""
    return get_mech_loader().get_mech_image(level, frame)

def get_mech_animation(level: int) -> Optional[bytes]:
    """Convenience function zum Abrufen einer Mech-Animation."""
    return get_mech_loader().get_mech_animation(level)