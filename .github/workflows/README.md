# 🚀 GitHub Actions Setup für Multi-Platform DDC

Diese Workflows ermöglichen automatisches Docker Hub Publishing für alle DDC-Plattformen.

## 📋 **Setup-Anweisungen**

### **1. Docker Hub Repositories erstellen**

Erstellen Sie diese Repositories auf [Docker Hub](https://hub.docker.com):

| Repository | Beschreibung |
|------------|--------------|
| `dockerdiscordcontrol/ddc` | Universal/Unraid Version |
| `dockerdiscordcontrol/ddc-windows` | Windows-optimierte Version |
| `dockerdiscordcontrol/ddc-linux` | Linux-optimierte Version |
| `dockerdiscordcontrol/ddc-mac` | macOS-optimierte Version |

### **2. GitHub Secrets konfigurieren**

Für **JEDES Repository** diese Secrets hinzufügen:

1. Gehe zu **Settings** → **Secrets and variables** → **Actions**
2. Füge diese Secrets hinzu:
   - `DOCKER_HUB_USERNAME`: Dein Docker Hub Benutzername
   - `DOCKER_HUB_ACCESS_TOKEN`: Docker Hub Access Token

### **3. Workflow-Dateien kopieren**

**Für jedes Repository die entsprechende Workflow-Datei kopieren:**

#### **DockerDiscordControl (Universal)**
```bash
# Kopiere: docker-publish.yml
# Nach: .github/workflows/docker-publish.yml
```

#### **DockerDiscordControl-Windows**
```bash
# Kopiere: docker-publish-windows.yml
# Nach: .github/workflows/docker-publish.yml
# Umbenenne IMAGE_NAME wenn nötig
```

#### **DockerDiscordControl-Linux**
```bash
# Kopiere: docker-publish-linux.yml
# Nach: .github/workflows/docker-publish.yml
```

#### **DockerDiscordControl-Mac**
```bash
# Kopiere: docker-publish-mac.yml
# Nach: .github/workflows/docker-publish.yml
```

### **4. Actions aktivieren**

1. Gehe zu **Actions** Tab im Repository
2. Klicke **"I understand my workflows, go ahead and enable them"**
3. Workflows werden bei Push/Tag automatisch ausgelöst

## 🎯 **Trigger-Events**

Die Workflows werden ausgelöst bei:
- **Push zu main**: Erstellt `latest` Tag
- **Git Tags** (`v*.*.*`): Erstellt versionierte Tags
- **Manual Dispatch**: Manueller Trigger mit Custom Tag

## 🏷️ **Tag-Schema**

| Repository | Tags |
|------------|------|
| **ddc** | `latest`, `unraid`, `v1.0.3` |
| **ddc-windows** | `latest`, `windows`, `v1.0.0-windows` |
| **ddc-linux** | `latest`, `linux`, `ubuntu`, `v1.0.0-linux` |
| **ddc-mac** | `latest`, `mac`, `macos`, `apple-silicon`, `v1.0.0-mac` |

## 🔧 **Multi-Architecture Support**

Alle Images werden für folgende Architekturen gebaut:
- `linux/amd64` (Intel/AMD)
- `linux/arm64` (Apple Silicon, ARM servers)

## 📊 **Monitoring**

Nach erfolgreichem Build:
- **GitHub Actions Tab**: Build-Status und Logs
- **Docker Hub**: Automatisch gepushte Images
- **Pull Requests**: Test-Builds ohne Push

## 🚨 **Troubleshooting**

**Build fails?**
- Prüfe Docker Hub Credentials
- Stelle sicher, dass Dockerfile existiert
- Prüfe Repository-Berechtigungen

**Push fails?**
- Prüfe Docker Hub Repository existiert
- Prüfe Access Token Berechtigungen
- Prüfe Repository ist public oder du hast Push-Rechte

## 🎉 **Erfolgreiche Einrichtung**

Nach Setup können Benutzer Images ziehen mit:

```bash
# Universal/Unraid
docker pull dockerdiscordcontrol/ddc:latest

# Windows
docker pull dockerdiscordcontrol/ddc-windows:latest

# Linux  
docker pull dockerdiscordcontrol/ddc-linux:latest

# macOS
docker pull dockerdiscordcontrol/ddc-mac:latest
``` 