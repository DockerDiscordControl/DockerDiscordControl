# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Spam Protection Service - Clean service architecture for rate limiting and spam protection
"""

import json
import threading
import time
from collections import deque
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Any, Optional
import discord
from utils.logging_utils import get_module_logger

logger = get_module_logger('spam_protection_service')

@dataclass(frozen=True)
class SpamProtectionConfig:
    """Immutable spam protection configuration data structure."""
    command_cooldowns: Dict[str, int]
    button_cooldowns: Dict[str, int]
    global_enabled: bool
    max_commands_per_minute: int
    max_buttons_per_minute: int
    cooldown_message: bool
    log_violations: bool

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SpamProtectionConfig':
        """Create SpamProtectionConfig from dictionary data."""
        return cls(
            command_cooldowns=dict(data.get('command_cooldowns', {})),
            button_cooldowns=dict(data.get('button_cooldowns', {})),
            global_enabled=bool(data.get('global_settings', {}).get('enabled', True)),
            max_commands_per_minute=int(data.get('global_settings', {}).get('max_commands_per_minute', 20)),
            max_buttons_per_minute=int(data.get('global_settings', {}).get('max_buttons_per_minute', 30)),
            cooldown_message=bool(data.get('global_settings', {}).get('cooldown_message', True)),
            log_violations=bool(data.get('global_settings', {}).get('log_violations', True))
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert SpamProtectionConfig to dictionary for storage."""
        return {
            'command_cooldowns': self.command_cooldowns,
            'button_cooldowns': self.button_cooldowns,
            'global_settings': {
                'enabled': self.global_enabled,
                'max_commands_per_minute': self.max_commands_per_minute,
                'max_buttons_per_minute': self.max_buttons_per_minute,
                'cooldown_message': self.cooldown_message,
                'log_violations': self.log_violations
            }
        }

@dataclass(frozen=True)
class ServiceResult:
    """Standard service result wrapper."""
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None

class SpamProtectionService:
    """Clean service for managing spam protection and rate limiting."""

    def __init__(self, config_dir: Optional[str] = None):
        """Initialize the spam protection service.

        Args:
            config_dir: Directory to store config files. Defaults to config/
        """
        if config_dir is None:
            # Robust absolute path relative to project root
            try:
                base_dir = Path(__file__).parents[2]
                config_dir = base_dir / "config"
            except Exception:
                config_dir = Path("config")
        else:
            config_dir = Path(config_dir)

        self.config_dir = config_dir
        self.config_dir.mkdir(parents=True, exist_ok=True)
        # Updated: Use channels_config.json as single source for spam protection
        self.config_file = self.config_dir / "channels_config.json"

        # In-memory cooldown tracking
        self._user_cooldowns: Dict[str, float] = {}

        # Gleitendes Minutenfenster je Nutzer und Art:
        # {(user_id, ist_befehl): deque[zeitstempel]}. Getrennte Eimer, weil
        # das Panel zwei Grenzen fuehrt (max_commands_per_minute und
        # max_buttons_per_minute). Eigene Sperre, weil dieser Dienst aus dem
        # Waitress-Faden (main_routes.py) UND aus der Bot-Schleife gerufen wird;
        # _user_cooldowns daneben ist ungesichert - ein eigener Befund, der hier
        # nicht nebenbei mitgeaendert wird.
        self._minutenfenster: Dict[tuple, deque] = {}
        self._fenster_sperre = threading.Lock()

        logger.info(f"Spam protection service initialized: {self.config_dir}")

    def get_config(self) -> ServiceResult:
        """Get spam protection configuration from channels_config.json.

        Returns:
            ServiceResult with SpamProtectionConfig data or error
        """
        try:
            if not self.config_file.exists():
                # Return default config
                default_config = self._get_default_config()
                return ServiceResult(success=True, data=default_config)

            with open(self.config_file, 'r', encoding='utf-8') as f:
                channels_data = json.load(f)

            # Extract spam_protection section from channels_config.json
            spam_data = channels_data.get('spam_protection', {})
            config = SpamProtectionConfig.from_dict(spam_data)
            return ServiceResult(success=True, data=config)

        except (AttributeError, IOError, KeyError, OSError, PermissionError, RuntimeError, TypeError, discord.Forbidden, discord.HTTPException, discord.NotFound, json.JSONDecodeError) as e:
            error_msg = f"Error loading spam protection config: {e}"
            logger.error(error_msg)
            return ServiceResult(success=False, error=error_msg)

    def save_config(self, config: SpamProtectionConfig) -> ServiceResult:
        """Save spam protection configuration to channels_config.json.

        Args:
            config: SpamProtectionConfig to save

        Returns:
            ServiceResult indicating success or failure
        """
        try:
            # Load existing channels_config.json
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    channels_data = json.load(f)
            else:
                channels_data = {}

            # Update spam_protection section
            channels_data['spam_protection'] = config.to_dict()

            # Atomic write
            temp_file = self.config_file.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(channels_data, f, indent=2, ensure_ascii=False)
            temp_file.replace(self.config_file)

            logger.info("Saved spam protection configuration to channels_config.json")
            return ServiceResult(success=True, data=config)

        except (IOError, OSError, PermissionError, RuntimeError, discord.Forbidden, discord.HTTPException, discord.NotFound, json.JSONDecodeError) as e:
            error_msg = f"Error saving spam protection config: {e}"
            logger.error(error_msg)
            return ServiceResult(success=False, error=error_msg)

    def is_enabled(self) -> bool:
        """Check if spam protection is enabled."""
        config_result = self.get_config()
        if config_result.success:
            return config_result.data.global_enabled
        return True  # Default to enabled if config can't be loaded

    def get_command_cooldown(self, command_name: str) -> int:
        """Get cooldown for a specific command."""
        config_result = self.get_config()
        if config_result.success:
            return config_result.data.command_cooldowns.get(command_name, 5)
        return 5

    def get_button_cooldown(self, button_name: str) -> int:
        """Get cooldown for a specific button."""
        config_result = self.get_config()
        if config_result.success:
            # Check for exact match first
            if button_name in config_result.data.button_cooldowns:
                return config_result.data.button_cooldowns[button_name]

            # Check for Mech button patterns (e.g., mech_donate_123456 -> mech_donate)
            if button_name.startswith('mech_'):
                parts = button_name.split('_')
                if len(parts) >= 2:
                    # Try patterns like mech_expand_channelid -> mech_expand
                    pattern = f"{parts[0]}_{parts[1]}"
                    if pattern in config_result.data.button_cooldowns:
                        return config_result.data.button_cooldowns[pattern]

            # Default cooldown
            return 5
        return 5

    def load_settings(self) -> ServiceResult:
        """Reload spam protection settings from config file.

        This method provides compatibility with the old manager interface.
        The service automatically loads settings on each access, so this just
        forces a config reload and returns the result.

        Returns:
            ServiceResult indicating success or failure
        """
        return self.get_config()

    # "Befehl oder Knopf?" entscheidet der AUFRUFER, nicht der Name.
    #
    # Bis hierher entschied eine fest verdrahtete Namensliste (serverstatus,
    # ss, control, info, help, ping, donate, command, language, forceupdate,
    # start, stop, restart). Hiess ein KNOPF wie ein Befehl, bremste er nach
    # dem BEFEHLS-Regler und zaehlte ins Befehls-Minutenfenster: der Info-Knopf
    # 5 s statt 3 s, der Hilfe-Knopf 3 s statt 5 s, der Neustart-Knopf 15 s
    # statt 20 s. Der Betreiber stellte im Panel den Knopf-Regler ein, und er
    # bewegte nichts. InfoDropdownButton und HelpButton hat erst die Umstellung
    # auf diesen Dienst (Commit 3785fc0) in diese Liste geschickt - vorher
    # fragten sie ausdruecklich get_button_cooldown.
    #
    # Alle Aufrufer dieser Methoden sind Knoepfe (gemessen; Befehle bremsen
    # ueber _check_spam_protection in docker_control.py). Knopf ist deshalb die
    # Vorgabe, und ein Befehl weist sich mit art="befehl" aus. Die Liste
    # entfaellt samt ihren Macken ('ss' stand in keinem Woerterbuch,
    # 'donatebroadcast' und 'info_edit' fehlten).
    _ARTEN = ("knopf", "befehl")

    _FENSTER_SEKUNDEN = 60.0

    @classmethod
    def _ist_befehl(cls, art: str) -> bool:
        """Prueft die Art LAUT: Ein Tippfehler wirft, statt still als Knopf zu gelten."""
        if art not in cls._ARTEN:
            raise ValueError(f"art muss eine von {cls._ARTEN} sein, nicht {art!r}")
        return art == "befehl"

    @staticmethod
    def _schluessel(user_id: int, action_type: str, ist_befehl: bool) -> str:
        """Eigener Schluesselraum fuer Befehle.

        Knoepfe behalten ihren bisherigen Schluessel "<nutzer>:<name>". Befehle
        bekommen "<nutzer>:befehl:<name>" - sonst teilten sich /info und der
        Info-KNOPF einen Eimer, sobald beide ueber diesen Dienst bremsen.
        """
        if ist_befehl:
            return f"{user_id}:befehl:{action_type}"
        return f"{user_id}:{action_type}"

    def _abklingdauer(self, action_type: str, ist_befehl: bool) -> int:
        """Abklingzeit je Aktion - aus dem Woerterbuch der angegebenen Art."""
        if ist_befehl:
            return self.get_command_cooldown(action_type)
        return self.get_button_cooldown(action_type)

    def _minutengrenze(self, ist_befehl: bool) -> int:
        """Die Grenze aus dem Panel. Faellt der Zugriff aus, gilt die Vorgabe."""
        ergebnis = self.get_config()
        config = ergebnis.data if ergebnis.success else self._get_default_config()
        return config.max_commands_per_minute if ist_befehl else config.max_buttons_per_minute

    @classmethod
    def _fenster_beschneiden(cls, eimer, jetzt: float) -> None:
        """Wirft alles aelter als eine Minute weg. Beim LESEN wie beim SCHREIBEN.

        Nur beim Schreiben aufzuraeumen waere ein Fehler: Wer die Grenze
        erreicht und dann nichts mehr tut, bliebe dauerhaft gesperrt, weil ohne
        neuen Eintrag nie beschnitten wuerde.
        """
        grenzzeit = jetzt - cls._FENSTER_SEKUNDEN
        while eimer and eimer[0] <= grenzzeit:
            eimer.popleft()

    def _fenster_ueberschritten(self, user_id: int, ist_befehl: bool, jetzt: float) -> bool:
        with self._fenster_sperre:
            eimer = self._minutenfenster.get((user_id, ist_befehl))
            if not eimer:
                return False
            self._fenster_beschneiden(eimer, jetzt)
            return len(eimer) >= self._minutengrenze(ist_befehl)

    def _fenster_restzeit(self, user_id: int, ist_befehl: bool, jetzt: float) -> float:
        """Wie lange, bis wieder Platz im Fenster ist."""
        with self._fenster_sperre:
            eimer = self._minutenfenster.get((user_id, ist_befehl))
            if not eimer:
                return 0.0
            self._fenster_beschneiden(eimer, jetzt)
            if len(eimer) < self._minutengrenze(ist_befehl):
                return 0.0
            # Der aelteste Eintrag faellt zuerst heraus.
            return max(0.0, self._FENSTER_SEKUNDEN - (jetzt - eimer[0]))

    def _fenster_eintragen(self, user_id: int, ist_befehl: bool, jetzt: float) -> None:
        with self._fenster_sperre:
            eimer = self._minutenfenster.setdefault((user_id, ist_befehl), deque())
            self._fenster_beschneiden(eimer, jetzt)
            eimer.append(jetzt)
            # Leere Eimer wegraeumen, sonst waechst die aeussere Ablage je
            # Nutzer unbegrenzt - dieselbe Vorsorge wie das 300-Sekunden-
            # Aufraeumen in add_user_cooldown.
            for schluessel in [k for k, v in self._minutenfenster.items() if not v]:
                del self._minutenfenster[schluessel]

    def is_on_cooldown(self, user_id: int, action_type: str, art: str = "knopf") -> bool:
        """Check if user is on cooldown for specific action.

        Args:
            user_id: Discord user ID
            action_type: Name of the button or command
            art: "knopf" (default) or "befehl"

        Returns:
            True if user is on cooldown, False otherwise
        """
        ist_befehl = self._ist_befehl(art)
        if not self.is_enabled():
            return False

        current_time = time.time()

        # Die Minutengrenze aus dem Panel. Bis hierher wurden
        # max_commands_per_minute und max_buttons_per_minute gespeichert, im
        # Panel angezeigt und ueber to_dict/from_dict sauber durchgereicht -
        # aber NIE abgefragt. Es gab keine Stelle, an der ein Druck gezaehlt
        # wurde; die Abklingzeit je Knopf merkt sich nur den LETZTEN Zeitpunkt.
        if self._fenster_ueberschritten(user_id, ist_befehl, current_time):
            return True

        cooldown_key = self._schluessel(user_id, action_type, ist_befehl)
        last_used = self._user_cooldowns.get(cooldown_key, 0)
        return (current_time - last_used) < self._abklingdauer(action_type, ist_befehl)

    def get_remaining_cooldown(self, user_id: int, action_type: str, art: str = "knopf") -> float:
        """Get remaining cooldown time for user action.

        Args:
            user_id: Discord user ID
            action_type: Name of the button or command
            art: "knopf" (default) or "befehl"

        Returns:
            Remaining cooldown time in seconds
        """
        ist_befehl = self._ist_befehl(art)
        if not self.is_enabled():
            return 0.0

        current_time = time.time()

        cooldown_key = self._schluessel(user_id, action_type, ist_befehl)
        last_used = self._user_cooldowns.get(cooldown_key, 0)
        rest_aktion = max(0.0, self._abklingdauer(action_type, ist_befehl) - (current_time - last_used))

        # Ohne den Fensteranteil stuende beim Nutzer "bitte warte 0.0 Sekunden",
        # wenn die Abweisung von der Minutengrenze kommt: Ein frisch gedrueckter
        # Knopf hat in _user_cooldowns gar keinen Eintrag. Alle Aufrufer fragen
        # direkt nach is_on_cooldown hier nach.
        rest_fenster = self._fenster_restzeit(user_id, ist_befehl, current_time)

        return max(rest_aktion, rest_fenster)

    def add_user_cooldown(self, user_id: int, action_type: str, art: str = "knopf") -> None:
        """Add user to cooldown for specific action.

        Args:
            user_id: Discord user ID
            action_type: Name of the button or command
            art: "knopf" (default) or "befehl"
        """
        ist_befehl = self._ist_befehl(art)
        if not self.is_enabled():
            return

        current_time = time.time()
        cooldown_key = self._schluessel(user_id, action_type, ist_befehl)
        self._user_cooldowns[cooldown_key] = current_time

        # Gezaehlt wird der ANGENOMMENE Druck, nicht die Nachfrage. Zaehlte
        # schon is_on_cooldown mit, verbrauchte jede abgewiesene Wiederholung
        # weiteres Kontingent - wer einmal gebremst wurde, kaeme nie wieder
        # heraus.
        self._fenster_eintragen(user_id, ist_befehl, current_time)

        # Clean old cooldowns (older than 5 minutes)
        old_keys = [key for key, timestamp in self._user_cooldowns.items()
                   if current_time - timestamp > 300]
        for key in old_keys:
            del self._user_cooldowns[key]

    def _get_default_config(self) -> SpamProtectionConfig:
        """Get default spam protection configuration."""
        return SpamProtectionConfig(
            command_cooldowns={
                "control": 5,
                "serverstatus": 30,
                "info": 5,
                "info_edit": 10,
                "help": 3,
                "ping": 3,
                "donate": 5,
                "donatebroadcast": 60,
                "command": 5,
                "language": 30,
                "forceupdate": 60,
                "start": 10,
                "stop": 10,
                "restart": 15
            },
            button_cooldowns={
                "start": 10,
                "stop": 10,
                "restart": 20,
                "info": 3,
                "refresh": 5,
                "logs": 10,
                "live_refresh": 5,
                "auto_refresh": 5,
                # Diese vier werden von lebenden Knoepfen angefordert
                # (control_ui.py:1791 admin, :2102 help, :1258 task_delete;
                # status_info_integration.py:1190 tasks), standen hier aber
                # nicht. get_button_cooldown:186 lieferte dafuer stumm 5
                # Sekunden - der Betreiber konnte den Wert weder sehen noch
                # aendern. "help" war dabei besonders irrefuehrend: Das Panel
                # zeigt einen /help-Regler (3), der aber den BEFEHL steuert und
                # nicht den Knopf; beide Namen sind gleich, die Woerterbuecher
                # verschieden.
                # Vorgabe 5 ist genau das, was die Ersatzregel heute liefert -
                # KEINE Anhebung, nur Sichtbarkeit. Erhoehen bestimmt das Panel.
                "admin": 5,
                "help": 5,
                "tasks": 5,
                "task_delete": 5,
                # Die drei Info-Knoepfe in status_info_integration.py fuehrten
                # ihre Abklingzeit selbst (button_protected_edit_<n>,
                # button_info_<n>, button_protected_<n> im Woerterbuch des Cogs)
                # und holten die DAUER gemeinsam unter "info". Sie haben also
                # drei GETRENNTE Eimer bei gleicher Dauer. Damit die Umstellung
                # auf den Dienst daran nichts aendert, bekommt jeder seinen
                # eigenen Namen - und den Wert 3, exakt den von "info".
                # Ohne Eintrag griffe die 5-Sekunden-Ersatzregel, und die
                # Knoepfe waeren langsamer als vorher, ohne Beschluss.
                "protected_info_edit": 3,
                "edit_info": 3,
                "protected_info": 3,
                "mech_expand": 3,
                "mech_collapse": 2,
                "mech_donate": 10,
                "mech_history": 5,
                # MechDetailsButton bremste frueher gar nicht und hatte keinen
                # Regler. 5 wie mech_history, dem verwandten privaten Blick -
                # zugleich die Ersatzregel, der Eintrag macht den Wert also
                # erst sichtbar und einstellbar.
                "mech_details": 5,
                "mech_display": 3,
                "mech_story": 5,
                "mech_music": 8
            },
            global_enabled=True,
            max_commands_per_minute=20,
            # 30, nicht 35: Fuer dieses eine Feld nannten drei Stellen zwei
            # verschiedene Vorgaben - from_dict (:41) und das Panel
            # (_spam_protection_modal.html:51) sagen 30, hier stand 35. Welche
            # Zahl galt, hing damit davon ab, ob config/channels_config.json
            # existiert: fehlt sie, kommt die Vorgabe von hier (get_config:103-106),
            # ist sie da, aus from_dict. Der Betreiber las im Panel eine andere
            # Zahl als die, nach der gebremst wurde. Die Befehlsgrenze daneben
            # war an allen drei Stellen schon einig (20) und bleibt unangetastet.
            # Das ist eine Vereinheitlichung, KEINE Anhebung: Welcher Wert gilt,
            # bestimmt weiterhin das Panel.
            max_buttons_per_minute=30,
            cooldown_message=True,
            log_violations=True
        )

# Singleton instance
_spam_protection_service = None

def get_spam_protection_service() -> SpamProtectionService:
    """Get the global spam protection service instance.

    Returns:
        SpamProtectionService instance
    """
    global _spam_protection_service
    if _spam_protection_service is None:
        _spam_protection_service = SpamProtectionService()
    return _spam_protection_service
