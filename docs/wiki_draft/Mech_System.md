# The Mech System

The **Mech System** is the heart of DDC's community engagement features. It gamifies the support for your server by visualizing donations and activity through an evolving virtual robot.

## Evolution Mechanics

The Mech starts as a scrappy Level 1 robot and can evolve up to a divine Level 11 entity.

### Progression
*   **Experience (XP)**: Every donation contributes to the Mech's evolution progress.
*   **Levels**: There are 11 distinct evolution levels.
    *   **Levels 1-3**: Early stages (Scrappy/Basic).
    *   **Levels 4-6**: Intermediate stages (Enhanced/Armored).
    *   **Levels 7-9**: Advanced stages (High-Tech/Futuristic).
    *   **Level 10**: Master Mech.
    *   **Level 11**: Divine/Transcendent State (The ultimate goal).

### Power & Decay
The Mech is powered by a "Power Level" which directly influences its animation speed.

*   **Daily Decay**: The Mech loses **1.0 Power per day** automatically. This requires consistent community support to maintain.
*   **Offline State**: If Power drops to **0.0**, the Mech goes offline (Rest animation).
    *   *Note:* Level 11 Mechs are immortal and never go offline.

## Animation Dynamics

The Mech's visual representation is dynamic and reacts to its Power Level.

### Speed System
The animation speed is not static. It fluctuates based on the current Power Level relative to the maximum capacity for that level.

*   **Base Speed**: 8 FPS (Frames Per Second).
*   **Minimum Speed**: 70% of base speed (Low Power).
*   **Maximum Speed**: 130% of base speed (Overcharged/High Power).

This creates a visual feedback loop: A fast-moving Mech indicates a healthy, well-supported server, while a sluggish Mech signals a need for support.

### Visual Modes
*   **Status Overview**: A compact, optimized animation shown in the server status embed.
*   **Big Display**: A full-resolution, high-detail animation shown when expanding the Mech view or in the Web UI.
*   **Shadow**: A silhouette shown for locked evolution levels in the history view.

## Interaction

Users can interact with the Mech via Discord buttons:
*   **Donate**: Simulates a donation (or links to a real donation page) to increase Power.
*   **History**: View all unlocked Mech evolutions.
*   **Status**: Check current stats like Speed, Decay Rate, and Next Level progress.
