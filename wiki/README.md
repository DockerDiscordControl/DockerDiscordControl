# DDC Wiki Content

This directory contains the detailed documentation content that should be copied to the GitHub Wiki.

## How to Use These Files

1. **Enable GitHub Wiki**
   - Go to your GitHub repository
   - Navigate to Settings → General
   - Scroll down to "Features" section
   - Check "Wikis" to enable it

2. **Copy Content to Wiki**
   - Go to the "Wiki" tab in your repository
   - Create new pages with the exact names listed below
   - Copy the content from each `.md` file to the corresponding wiki page

## Wiki Pages Structure

| Wiki Page Name | Source File | Description |
|----------------|-------------|-------------|
| **Home** | Create manually | Main wiki landing page with overview |
| **Discord-Bot-Setup** | `Discord-Bot-Setup.md` | Complete Discord bot creation guide |
| **Installation-Guide** | `Installation-Guide.md` | Detailed installation for all platforms |
| **Configuration** | `Configuration.md` | Web UI configuration guide |
| **Task-System** | `Task-System.md` | Automated scheduling system |
| **Performance-and-Architecture** | `Performance-and-Architecture.md` | Performance optimizations & monitoring |
| **Troubleshooting** | `Troubleshooting.md` | Common issues & solutions |
| **Development** | `Development.md` | Contributing & development setup |
| **Security** | `Security.md` | Best practices & considerations |

## Wiki Navigation

Create a sidebar by adding a page called `_Sidebar` with this content:

```markdown
## 📚 DDC Documentation

### Getting Started
- [🚀 Installation Guide](Installation-Guide)
- [🤖 Discord Bot Setup](Discord-Bot-Setup)
- [⚙️ Configuration](Configuration)

### Features  
- [📅 Task System](Task-System)
- [🚀 Performance](Performance-and-Architecture)

### Help & Support
- [🔧 Troubleshooting](Troubleshooting)
- [🔒 Security](Security)
- [👩‍💻 Development](Development)

### Links
- [📖 Main Repository](https://github.com/DockerDiscordControl/DockerDiscordControl)
- [🌐 Homepage](https://ddc.bot)
```

## Benefits of This Structure

✅ **Cleaner Repository**: Main README is now only 96 lines (vs 568 lines)
✅ **Better Organization**: Each topic has its own dedicated page
✅ **Easier Maintenance**: Update documentation without cluttering repository
✅ **Better Navigation**: Wiki provides better search and linking
✅ **Professional Appearance**: More polished documentation structure

## Quick Start for Wiki Setup

1. Copy this entire `wiki/` folder content
2. Go to your GitHub repository's Wiki tab
3. Create pages with the exact names from the table above
4. Paste the corresponding file content
5. Create the `_Sidebar` for navigation
6. Create a `Home` page as the main landing page

## Future Wiki Pages to Add

Consider adding these additional pages as DDC grows:

- **API Reference** - If you add API endpoints
- **Plugin Development** - For future extensibility
- **FAQ** - Frequently asked questions
- **Changelog** - Detailed version history
- **Examples** - Configuration examples and use cases 