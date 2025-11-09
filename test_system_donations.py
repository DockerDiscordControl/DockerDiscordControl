#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Script: System Donations (Power-Only, No Evolution)

Demonstrates how to use system donations for community events,
achievements, and milestones that move the mech but don't
contribute to evolution progress.
"""

from services.mech.progress_service import get_progress_service


def main():
    print("=" * 70)
    print("SYSTEM DONATIONS DEMO")
    print("=" * 70)
    print()

    ps = get_progress_service()

    # Show initial state
    initial = ps.get_state()
    print("📊 INITIAL STATE")
    print(f"   Level: {initial.level}")
    print(f"   Evolution: ${initial.evo_current:.2f} / ${initial.evo_max:.2f}")
    print(f"   Power: ${initial.power_current:.2f}")
    print()

    # Example 1: Normal donation (affects both bars)
    print("💰 NORMAL DONATION: $5.00 from User")
    print("   (Increases both Evolution AND Power)")
    state1 = ps.add_donation(amount_dollars=5.0, donor="Test User")
    print(f"   Evolution: ${state1.evo_current:.2f} / ${state1.evo_max:.2f}  ✅ +$5.00")
    print(f"   Power: ${state1.power_current:.2f}  ✅ +$5.00")
    print()

    # Example 2: Community milestone event
    print("🎉 SYSTEM EVENT: Server 100 Members")
    print("   (Increases ONLY Power, NOT Evolution)")
    state2 = ps.add_system_donation(
        amount_dollars=3.0,
        event_name="Server 100 Members",
        description="Community milestone achieved!"
    )
    print(f"   Evolution: ${state2.evo_current:.2f} / ${state2.evo_max:.2f}  ❌ unchanged")
    print(f"   Power: ${state2.power_current:.2f}  ✅ +$3.00")
    print()

    # Example 3: Bot birthday
    print("🎂 SYSTEM EVENT: Bot Birthday 2025")
    print("   (Increases ONLY Power, NOT Evolution)")
    state3 = ps.add_system_donation(
        amount_dollars=2.0,
        event_name="Bot Birthday 2025",
        description="Happy 1st birthday!"
    )
    print(f"   Evolution: ${state3.evo_current:.2f} / ${state3.evo_max:.2f}  ❌ unchanged")
    print(f"   Power: ${state3.power_current:.2f}  ✅ +$2.00")
    print()

    # Example 4: Achievement unlock
    print("🏆 SYSTEM EVENT: 1000 Containers Started")
    print("   (Increases ONLY Power, NOT Evolution)")
    state4 = ps.add_system_donation(
        amount_dollars=1.5,
        event_name="1000 Containers Started",
        description="Achievement unlocked!"
    )
    print(f"   Evolution: ${state4.evo_current:.2f} / ${state4.evo_max:.2f}  ❌ unchanged")
    print(f"   Power: ${state4.power_current:.2f}  ✅ +$1.50")
    print()

    # Final summary
    print("=" * 70)
    print("📈 SUMMARY")
    print("=" * 70)
    print(f"Evolution Progress:")
    print(f"  - Started at: ${initial.evo_current:.2f}")
    print(f"  - Normal donations: +$5.00")
    print(f"  - System events: +$0.00 (doesn't affect evolution!)")
    print(f"  - Current: ${state4.evo_current:.2f}")
    print()
    print(f"Power Progress:")
    print(f"  - Started at: ${initial.power_current:.2f}")
    print(f"  - Normal donations: +$5.00")
    print(f"  - System events: +$6.50 ($3 + $2 + $1.50)")
    print(f"  - Current: ${state4.power_current:.2f}")
    print()
    print("✅ Mech moves from both normal donations AND system events")
    print("✅ But only normal donations count toward evolution goals!")
    print()

    # Use case examples
    print("=" * 70)
    print("💡 USE CASES FOR SYSTEM DONATIONS")
    print("=" * 70)
    print("1. Community Milestones:")
    print("   - Server reaches 100/500/1000 members")
    print("   - First time hitting 100 online users")
    print()
    print("2. Achievements:")
    print("   - 1000 containers started")
    print("   - 10,000 commands executed")
    print("   - Uptime milestones")
    print()
    print("3. Special Events:")
    print("   - Bot birthday")
    print("   - Server anniversary")
    print("   - Holiday bonuses")
    print()
    print("4. Automatic Rewards:")
    print("   - Daily login bonuses")
    print("   - Activity rewards")
    print("   - Referral bonuses")
    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
