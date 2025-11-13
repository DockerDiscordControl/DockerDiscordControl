#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mech Reset Service - Easy reset functionality for testing and development

This service provides simple methods to reset the Mech system to Level 1
without having to manually edit JSON files.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class ResetResult:
    """Result of a reset operation."""
    success: bool
    message: str
    details: Optional[Dict[str, Any]] = None

class MechResetService:
    """Service for resetting Mech system for testing/development."""

    def __init__(self, config_dir: str = "config"):
        """Initialize the Mech Reset Service.

        Args:
            config_dir: Directory containing config files
        """
        if not config_dir.startswith('/'):
            # Relative path - make it absolute
            base_dir = Path(__file__).parent.parent.parent
            self.config_dir = base_dir / config_dir
        else:
            self.config_dir = Path(config_dir)

        # SINGLE POINT OF TRUTH: Only donations file needed now
        self.donations_file = self.config_dir / "mech_donations.json"

        # Optional files that may exist
        self.mech_state_file = self.config_dir / "mech_state.json"
        self.evolution_mode_file = self.config_dir / "evolution_mode.json"

        # DEPRECATED: No longer needed with Single Point of Truth
        self.achieved_levels_file = self.config_dir / "achieved_levels.json"

        logger.info(f"Mech Reset Service initialized for Single Point of Truth: {self.config_dir}")

    def full_reset(self) -> ResetResult:
        """
        SINGLE POINT OF TRUTH: Perform a complete Mech reset to Level 1.

        With the new architecture, we only need to clear donations!
        All level information is derived from donation history.

        Returns:
            ResetResult with success status and message
        """
        try:
            results = []

            # SINGLE POINT OF TRUTH: Only need to clear donations
            donations_result = self.clear_all_donations()
            results.append(f"Donations: {donations_result.message}")

            # Optional: Reset mech state (for Discord channel states)
            state_result = self.reset_mech_state()
            results.append(f"Mech State: {state_result.message}")

            # Optional: Reset evolution mode (difficulty settings)
            evolution_result = self.reset_evolution_mode()
            results.append(f"Evolution Mode: {evolution_result.message}")

            # Optional: Clean up deprecated achieved_levels.json
            cleanup_result = self.cleanup_deprecated_files()
            results.append(f"Cleanup: {cleanup_result.message}")

            success = all([donations_result.success, state_result.success,
                          evolution_result.success, cleanup_result.success])

            if success:
                message = "✅ Complete Mech reset to Level 1 successful! (Single Point of Truth)"
                logger.info("Full Mech reset completed successfully with new architecture")
            else:
                message = "⚠️ Mech reset completed with some warnings"
                logger.warning("Mech reset completed with some issues")

            return ResetResult(
                success=success,
                message=message,
                details={
                    "operations": results,
                    "architecture": "Single Point of Truth - donations only",
                    "timestamp": datetime.now().isoformat()
                }
            )

        except (RuntimeError, AttributeError) as e:
            # Orchestration errors (method call failures, attribute access)
            error_msg = f"❌ Error during full Mech reset: {e}"
            logger.error(error_msg, exc_info=True)
            return ResetResult(success=False, message=error_msg)

    def clear_all_donations(self) -> ResetResult:
        """Clear all donations from mech_donations.json.

        Returns:
            ResetResult with success status
        """
        try:
            donations_data = {
                "donations": []
            }

            with open(self.donations_file, 'w', encoding='utf-8') as f:
                json.dump(donations_data, f, indent=2, ensure_ascii=False)

            logger.info("Cleared all Mech donations")
            return ResetResult(success=True, message="All donations cleared")

        except (IOError, OSError) as e:
            # File I/O errors (writing donations file)
            error_msg = f"Error clearing donations: {e}"
            logger.error(error_msg, exc_info=True)
            return ResetResult(success=False, message=error_msg)

    def cleanup_deprecated_files(self) -> ResetResult:
        """
        SINGLE POINT OF TRUTH: Clean up deprecated achieved_levels.json file.

        This file is no longer needed with the new architecture.

        Returns:
            ResetResult with success status
        """
        try:
            removed_files = []

            # Remove deprecated achieved_levels.json
            if self.achieved_levels_file.exists():
                self.achieved_levels_file.unlink()
                removed_files.append("achieved_levels.json")
                logger.info("Removed deprecated achieved_levels.json")

            if removed_files:
                message = f"Removed deprecated files: {', '.join(removed_files)}"
            else:
                message = "No deprecated files to clean up"

            return ResetResult(success=True, message=message)

        except (IOError, OSError, PermissionError) as e:
            # File system errors (file deletion, permissions)
            error_msg = f"Error cleaning up deprecated files: {e}"
            logger.error(error_msg, exc_info=True)
            return ResetResult(success=False, message=error_msg)

    def reset_mech_state(self) -> ResetResult:
        """Reset mech state to default Level 1 state.

        Returns:
            ResetResult with success status
        """
        try:
            if self.mech_state_file.exists():
                with open(self.mech_state_file, 'r', encoding='utf-8') as f:
                    current_state = json.load(f)
            else:
                current_state = {}

            # Reset all glvl to 1 (Level 1) but keep channel structure
            if "last_glvl_per_channel" in current_state:
                for channel_id in current_state["last_glvl_per_channel"]:
                    current_state["last_glvl_per_channel"][channel_id] = 1

            # Update timestamp
            current_state["last_update"] = datetime.now().isoformat()

            # Ensure expanded states are false
            if "mech_expanded_states" in current_state:
                for channel_id in current_state["mech_expanded_states"]:
                    current_state["mech_expanded_states"][channel_id] = False

            with open(self.mech_state_file, 'w', encoding='utf-8') as f:
                json.dump(current_state, f, indent=2, ensure_ascii=False)

            logger.info("Reset Mech state to Level 1")
            return ResetResult(success=True, message="Mech state reset to Level 1")

        except (IOError, OSError) as e:
            # File I/O errors (reading/writing state file)
            error_msg = f"Error resetting Mech state: {e}"
            logger.error(error_msg, exc_info=True)
            return ResetResult(success=False, message=error_msg)
        except json.JSONDecodeError as e:
            # JSON parsing errors (corrupted state file)
            error_msg = f"Error parsing Mech state JSON: {e}"
            logger.error(error_msg, exc_info=True)
            return ResetResult(success=False, message=error_msg)
        except (KeyError, ValueError, TypeError) as e:
            # Data access/structure errors (unexpected JSON structure)
            error_msg = f"Error processing Mech state data: {e}"
            logger.error(error_msg, exc_info=True)
            return ResetResult(success=False, message=error_msg)

    def reset_evolution_mode(self) -> ResetResult:
        """Reset evolution mode to default settings.

        Returns:
            ResetResult with success status
        """
        try:
            if not self.evolution_mode_file.exists():
                return ResetResult(success=True, message="Evolution mode file not found (OK)")

            evolution_data = {
                "use_dynamic": False,
                "difficulty_multiplier": 1.0,
                "last_updated": datetime.now().isoformat()
            }

            with open(self.evolution_mode_file, 'w', encoding='utf-8') as f:
                json.dump(evolution_data, f, indent=2, ensure_ascii=False)

            logger.info("Reset evolution mode to defaults")
            return ResetResult(success=True, message="Evolution mode reset to defaults")

        except (IOError, OSError) as e:
            # File I/O errors (reading/writing evolution mode file)
            error_msg = f"Error resetting evolution mode: {e}"
            logger.error(error_msg, exc_info=True)
            return ResetResult(success=False, message=error_msg)

    def get_current_status(self) -> Dict[str, Any]:
        """
        SINGLE POINT OF TRUTH: Get current Mech system status.

        Calculates everything from donation history using new architecture.

        Returns:
            Dictionary with current status information
        """
        try:
            status = {}

            # Load donations (Single Point of Truth)
            if self.donations_file.exists():
                with open(self.donations_file, 'r', encoding='utf-8') as f:
                    donations_data = json.load(f)
                donations = donations_data.get("donations", [])

                status["donations_count"] = len(donations)

                # Calculate total donated amount
                total_donated = sum(int(d.get("amount", 0)) for d in donations)
                status["total_donated"] = total_donated

                # Calculate current level from donations
                current_level = 1
                level_upgrades = 0
                for donation in donations:
                    if donation.get('level_upgrade') and donation.get('level_reached'):
                        current_level = max(current_level, donation['level_reached'])
                        level_upgrades += 1

                status["current_level"] = current_level
                status["level_upgrades_count"] = level_upgrades

                # Calculate next level info
                if current_level < 11:
                    from services.mech.mech_service import MECH_LEVELS
                    if current_level < len(MECH_LEVELS):
                        next_level_threshold = MECH_LEVELS[current_level].threshold
                        status["next_level_threshold"] = next_level_threshold
                        status["amount_needed"] = max(0, next_level_threshold - total_donated)
                        status["next_level_name"] = MECH_LEVELS[current_level].name
                    else:
                        status["next_level_threshold"] = None
                        status["amount_needed"] = 0
                        status["next_level_name"] = "MAX LEVEL"
                else:
                    status["next_level_threshold"] = None
                    status["amount_needed"] = 0
                    status["next_level_name"] = "OMEGA MECH (MAX)"

            else:
                status["donations_count"] = 0
                status["total_donated"] = 0
                status["current_level"] = 1
                status["level_upgrades_count"] = 0
                status["next_level_threshold"] = 20
                status["amount_needed"] = 20
                status["next_level_name"] = "The Battle-Scarred Survivor"

            # Check mech state (Discord channel tracking)
            if self.mech_state_file.exists():
                with open(self.mech_state_file, 'r', encoding='utf-8') as f:
                    state_data = json.load(f)
                glvl_channels = state_data.get("last_glvl_per_channel", {})
                status["channels_tracked"] = len(glvl_channels)
                status["glvl_values"] = list(glvl_channels.values()) if glvl_channels else []
            else:
                status["channels_tracked"] = 0
                status["glvl_values"] = []

            # Add architecture info
            status["architecture"] = "Single Point of Truth"
            status["deprecated_files_exist"] = self.achieved_levels_file.exists()

            return status

        except (IOError, OSError) as e:
            # File I/O errors (reading donations, state files)
            logger.error(f"File I/O error getting Mech status: {e}", exc_info=True)
            return {"error": f"File I/O error: {str(e)}"}
        except json.JSONDecodeError as e:
            # JSON parsing errors (corrupted files)
            logger.error(f"JSON parsing error getting Mech status: {e}", exc_info=True)
            return {"error": f"JSON parsing error: {str(e)}"}
        except (ImportError, AttributeError) as e:
            # Service dependency errors (mech_service import)
            logger.error(f"Service dependency error getting Mech status: {e}", exc_info=True)
            return {"error": f"Service dependency error: {str(e)}"}
        except (ValueError, TypeError, KeyError) as e:
            # Data calculation/access errors (sum, dict access)
            logger.error(f"Data processing error getting Mech status: {e}", exc_info=True)
            return {"error": f"Data processing error: {str(e)}"}


# Singleton instance
_mech_reset_service = None

def get_mech_reset_service() -> MechResetService:
    """Get the global Mech Reset Service instance.

    Returns:
        MechResetService instance
    """
    global _mech_reset_service
    if _mech_reset_service is None:
        _mech_reset_service = MechResetService()
    return _mech_reset_service


# Convenience function for quick resets
def quick_mech_reset() -> ResetResult:
    """Quick function to reset Mech to Level 1.

    Returns:
        ResetResult with operation status
    """
    service = get_mech_reset_service()
    return service.full_reset()


if __name__ == "__main__":
    # CLI usage
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "reset":
        print("🔄 Performing Mech reset to Level 1...")
        result = quick_mech_reset()
        print(result.message)
        if result.details:
            for op in result.details.get("operations", []):
                print(f"  - {op}")
    else:
        service = get_mech_reset_service()
        status = service.get_current_status()
        print("📊 Current Mech Status:")
        for key, value in status.items():
            print(f"  - {key}: {value}")
        print("\nUsage: python mech_reset_service.py reset")