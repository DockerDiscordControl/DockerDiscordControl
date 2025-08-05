# Discord Bot Setup Guide

This guide walks you through creating and configuring a Discord bot for DockerDiscordControl.

## Step 1: Create Discord Application

1. **Go to Discord Developer Portal**
   - Visit [https://discord.com/developers/applications](https://discord.com/developers/applications)
   - Log in with your Discord account

2. **Create New Application**
   - Click "New Application"
   - Enter a name for your bot (e.g., "Docker Control Bot")
   - Click "Create"

## Step 2: Create Bot User

1. **Navigate to Bot Section**
   - In the left sidebar, click "Bot"
   - Click "Add Bot" (or "Create a Bot" on newer versions)
   - Confirm by clicking "Yes, do it!"

2. **Configure Bot Settings**
   - **Username**: Set a memorable bot username
   - **Avatar**: Upload a custom avatar (optional)
   - **Public Bot**: Disable this unless you want others to add your bot to their servers

## Step 3: Configure Bot Permissions

### Privileged Gateway Intents

**Important**: Enable these intents for full functionality:

1. **Server Members Intent**
   - Required for member management features
   - Toggle "Server Members Intent" to ON

2. **Message Content Intent** 
   - Required for message processing
   - Toggle "Message Content Intent" to ON

### Bot Permissions

When generating the invite URL, select these permissions:

**Essential Permissions:**
- ✅ View Channels
- ✅ Send Messages
- ✅ Embed Links
- ✅ Attach Files
- ✅ Read Message History
- ✅ Use Slash Commands
- ✅ Manage Messages (for editing status messages)

**Optional (for enhanced functionality):**
- Add Reactions (for interactive buttons)
- Manage Webhooks (for advanced integrations)

## Step 4: Get Bot Token

1. **Copy Bot Token**
   - In the "Bot" section, find "Token"
   - Click "Copy" to copy your bot token
   - **⚠️ Keep this token secure! Never share it publicly**

2. **Reset Token (if needed)**
   - If you accidentally expose your token, click "Regenerate"
   - This will invalidate the old token

## Step 5: Get Guild (Server) ID

1. **Enable Developer Mode**
   - In Discord, go to User Settings (gear icon)
   - Navigate to "Advanced"
   - Enable "Developer Mode"

2. **Copy Server ID**
   - Right-click on your server name
   - Select "Copy Server ID"
   - This is your Guild ID for DDC configuration

## Step 6: Generate Invite URL

1. **Go to OAuth2 Section**
   - In Discord Developer Portal, click "OAuth2" → "URL Generator"

2. **Select Scopes**
   - ✅ `bot`
   - ✅ `applications.commands`

3. **Select Bot Permissions**
   - Choose the permissions listed in Step 3
   - Or simply select "Administrator" for full access (less secure)

4. **Copy and Use Invite URL**
   - Copy the generated URL
   - Paste it in your browser
   - Select your server and authorize the bot

## Step 7: Configure DDC

In the DDC Web UI (`http://your-server:8374`):

1. **Discord Bot Token**: Paste your bot token
2. **Guild ID**: Paste your server ID
3. **Channel Configuration**: Set up channel permissions
4. **Save and Restart**: Save configuration and restart the container

## Common Issues

### Bot Not Responding
- **Check Token**: Ensure bot token is correct
- **Check Guild ID**: Verify server ID is correct
- **Check Permissions**: Bot needs appropriate permissions
- **Check Intents**: Enable required privileged intents

### Missing Slash Commands
- **Wait for Registration**: Commands can take up to 1 hour to appear
- **Check Permissions**: Bot needs "Use Slash Commands" permission
- **Restart Bot**: Try restarting the DDC container

### Permission Denied Errors
- **Check Channel Permissions**: Configure channel permissions in DDC Web UI
- **Bot Role Position**: Ensure bot role is high enough in server hierarchy
- **Channel Overrides**: Check channel-specific permission overrides

## Security Best Practices

1. **Keep Token Secure**
   - Never share your bot token
   - Use environment variables or secure configuration
   - Regenerate if accidentally exposed

2. **Limit Permissions**
   - Only grant necessary permissions
   - Use channel-specific permissions
   - Regularly audit bot access

3. **Monitor Activity**
   - Check DDC action logs regularly
   - Monitor unusual bot activity
   - Set up appropriate logging

## Next Steps

- [📖 Installation Guide](Installation-Guide) - Install DDC
- [⚙️ Configuration](Configuration) - Configure container permissions
- [Troubleshooting](Troubleshooting) - Common issues and solutions 