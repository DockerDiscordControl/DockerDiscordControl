# Status Info Integration for DDC

## Overview

The Status Info Integration feature brings smart container information display to status-only channels. This allows channels with limited permissions (only `/ss` for server status) to provide users with additional container information without compromising security by giving control permissions.

## Key Features

### 🔍 Smart Channel Detection
- Automatically detects status-only channels vs. control channels
- Uses different UI components based on channel permissions
- Maintains security boundaries between read-only and control access

### 📋 Enhanced Status Display
- Status embeds now include info indicators when container info is available
- Visual cues show users that additional information exists
- Seamless integration with existing status message format

### ℹ️ Interactive Info Button
- **Status-Only Channels**: Shows dedicated "Info" button for containers with info enabled
- **Control Channels**: Info features are integrated alongside existing control buttons
- Info button displays container information in ephemeral (private) messages

### 🌐 Comprehensive Information Display
- **Custom Information**: Displays custom text configured per container
- **Network Access**: Shows IP addresses (custom or auto-detected WAN IP)
- **Container Status**: Current state, uptime, and availability info
- **Metadata**: Container name, service details, and technical information

## Architecture

### Components

#### StatusInfoView
- `cogs/status_info_integration.py`
- Discord UI View specifically for status-only channels
- Only shows info button when container has info enabled
- Lightweight alternative to ControlView for read-only channels

#### StatusInfoButton
- Interactive button that displays container info in ephemeral messages
- Handles info embed generation and display
- Includes error handling and user feedback

#### Enhanced Status Embeds
- `create_enhanced_status_embed()` function
- Adds visual indicators to existing status embeds
- Maintains compatibility with existing status display format

### Integration Points

#### Status Handlers
- Modified `_generate_status_embed_and_view()` in `status_handlers.py`
- Smart view selection based on channel permissions
- Automatic embed enhancement for info-enabled containers

#### Permission System
- Leverages existing `_channel_has_permission()` function
- Distinguishes between control channels and status-only channels
- Maintains security boundaries while adding functionality

## Usage Scenarios

### Status-Only Channels
**Use Case**: Channels where users can view server status but not control containers

**Features**:
- Enhanced status embeds with info indicators
- Info button for containers with enabled info
- Read-only access to container information
- No control buttons (start/stop/restart)

### Control Channels
**Use Case**: Channels with full container control permissions

**Features**:
- Standard ControlView with all control buttons
- Enhanced embeds as additional feature
- Full control + info capabilities

## Configuration

### Container Info Setup
Container info is configured per container using:
1. **Web UI**: Modal configuration in "Container Selection & Bot Permissions" table
2. **Discord Commands**: `/info_edit <containername>` command in channels with control permissions

### Info Components
- **Enabled/Disabled**: Toggle info button availability
- **Show IP**: Display IP address information
- **Custom IP**: Override auto-detected IP with custom address/URL
- **Custom Text**: Free-form text for passwords, mods, player counts, etc.

### Channel Configuration
Channels are automatically detected based on permissions:
- **Status Permission Only**: Shows StatusInfoView with info button
- **Control Permission**: Shows ControlView with full controls + enhanced info

## Technical Implementation

### Performance Optimizations
- **Lazy Loading**: Info button only loads when clicked
- **Caching**: Leverages existing container status cache
- **Ephemeral Messages**: Info displays don't clutter channels
- **Async Operations**: Non-blocking IP detection and data loading

### Error Handling
- Graceful degradation when info cannot be loaded
- User-friendly error messages in ephemeral responses
- Logging for debugging while maintaining user experience

### Security Features
- **Ephemeral Display**: Info is only visible to the user who clicked
- **Permission Boundaries**: Status-only channels cannot control containers
- **Input Sanitization**: All custom text is properly sanitized
- **Rate Limiting**: Built-in protection against spam

## Benefits

### For Users
- **Enhanced Experience**: Richer information in status channels
- **Easy Access**: One-click info display without channel switching
- **Privacy**: Personal info viewing doesn't clutter public channels
- **Consistency**: Same info system across all channel types

### For Administrators
- **Security**: Maintains separation between status viewing and control
- **Flexibility**: Can enable info for specific containers as needed
- **Management**: Centralized info configuration through existing interfaces
- **Monitoring**: Full logging and error tracking

### For System
- **Performance**: Minimal overhead on existing status system
- **Compatibility**: Fully backward compatible with existing features
- **Scalability**: Efficient design for large container deployments
- **Maintenance**: Clean separation of concerns in codebase

## Example Use Cases

### Gaming Server Status Channel
- Shows server online/offline status
- Info button reveals:
  - Server IP and port
  - Current player count
  - Installed mods
  - Admin contact info

### Application Monitoring Channel
- Displays service health status
- Info button shows:
  - Service endpoints
  - Health check URLs
  - Maintenance schedules
  - Troubleshooting guides

### Development Environment Status
- Container status for dev services
- Info button provides:
  - Database connection strings
  - API endpoints
  - Development credentials
  - Setup instructions

## Migration Path

The Status Info Integration is **fully backward compatible**:

1. **Existing Channels**: Continue working exactly as before
2. **New Features**: Automatically available when container info is configured
3. **Gradual Adoption**: Can enable info for containers incrementally
4. **No Breaking Changes**: All existing functionality preserved

## Future Enhancements

### Planned Features
- **Custom Info Templates**: Pre-defined templates for common container types
- **Dynamic Info**: Real-time updating of info displays
- **Role-Based Info**: Different info visibility based on user roles
- **Info Categories**: Organized display of different types of information

### Extensibility
The modular design allows for easy extension:
- Additional info display formats
- Custom info sources and integrations
- Enhanced interactivity within security boundaries
- Integration with external monitoring systems