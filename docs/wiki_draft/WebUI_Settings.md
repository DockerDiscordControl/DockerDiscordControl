# Web UI Settings

The Web Dashboard provides a user-friendly interface to configure DDC. Access it at `http://<your-ip>:9374`.

## Main Settings
*   **Bot Configuration**: Set your Bot Token and Guild ID here.
*   **Docker Configuration**: Configure the path to the Docker socket and API timeouts.

## Spam Protection
DDC includes a robust spam protection system to prevent abuse of the bot buttons and commands. These settings are managed via the "Spam Protection" modal.

### Global Settings
*   **Enable Spam Protection**: Master switch to turn rate limiting on/off.
*   **Max Commands/Min**: Maximum number of commands allowed globally per minute (Default: `20`).
*   **Max Buttons/Min**: Maximum number of button interactions allowed globally per minute (Default: `30`).

### Cooldowns (Defaults)
You can configure individual cooldowns for each action type (in seconds):

| Action | Default Cooldown | Description |
| :--- | :--- | :--- |
| **Start/Stop** | `10s` | Managing containers (start/stop commands). |
| **Restart** | `15-20s` | Restarting containers. |
| **Refresh** | `5s` | Refreshing status displays. |
| **Info** | `3-5s` | Viewing container details. |
| **Mech Buttons** | `3-10s` | Various Mech interactions (donate, history, expand). |

*Note: Violations are logged if "Log Violations" is enabled.*

## Advanced Settings
These settings control the low-level performance and behavior of DDC.

### Performance Tuning
*   **Docker Cache Duration** (Default: `30s`): How long the container list is kept in memory. Increase this if you have many containers to reduce CPU load.
*   **Background Refresh Interval** (Default: `30s`): How often the bot updates its internal cache of container states in the background.
*   **Max Concurrent Tasks** (Default: `3`): Maximum number of scheduled tasks that can run simultaneously.

### Live Logs
*   **Enable Live Logs**: Allow viewing real-time container logs in the Web UI.
*   **Tail Lines** (Default: `50`): Number of past log lines to show when opening the log viewer.
*   **Auto Start**: Whether logs should start streaming immediately when the modal opens.

### Limits
*   **Max Containers Display** (Default: `100`): Limits the number of containers shown in the list to prevent UI lag on large systems.
*   **Docker API Timeout** (Default: `30s`): Maximum time to wait for a response from the Docker daemon before failing.
