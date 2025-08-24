# -*- coding: utf-8 -*-
from functools import lru_cache
from utils.config_loader import load_config
import logging
from utils.logging_utils import setup_logger

# <<< Logger setup using utility function >>>
logger = setup_logger('ddc.translation_manager', level=logging.DEBUG)
# Optional: Handler hinzufügen, falls nicht über Root-Logger konfiguriert
# if not logger.handlers:
#    ...

# Optimized translation management with caching
class TranslationManager:
    """Singleton class for translations with efficient caching"""
    _instance = None
    _translations = None
    _current_language = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TranslationManager, cls).__new__(cls)
            cls._instance._load_translations()
        return cls._instance

    def _load_translations(self):
        """Loads all translations into a dictionary cache"""
        self._translations = {
            # German
            'de': {
                # General texts
                "Docker Control Panel": "Docker Kontrollpanel",
                "Here you can control your Docker containers. Use the buttons below each server to perform actions.":
                    "Hier können Sie Ihre Docker-Container steuern. Verwenden Sie die Schaltflächen unter jedem Server, um Aktionen auszuführen.",
                "Available Commands": "Verfügbare Befehle",
                "Shows this control panel": "Zeigt dieses Kontrollpanel an",
                "Shows server status (shortcut: /ss)": "Zeigt den Serverstatus an (Kurzbefehl: /ss)",
                "Directly control a container": "Steuert einen Container direkt",
                "Shows help about available commands": "Zeigt Hilfe zu verfügbaren Befehlen an",
                "Shows the bot response time": "Zeigt die Antwortzeit des Bots an",
                "Edit container information": "Container-Informationen bearbeiten",
                "Container info is not configured for this container.": "Container-Info ist für diesen Container nicht konfiguriert.",
                "Container info is not enabled for **{display_name}**. Enable it in the web UI first.": "Container-Info ist für **{display_name}** nicht aktiviert. Aktivieren Sie es zuerst in der Web-UI.",
                "You don't have permission to view container info in this channel.": "Sie haben keine Berechtigung, Container-Informationen in diesem Kanal anzuzeigen.",
                "You do not have permission to edit container info in this channel.": "Sie haben keine Berechtigung, Container-Informationen in diesem Kanal zu bearbeiten.",
                "Container information is read-only in this channel.": "Container-Informationen sind in diesem Kanal schreibgeschützt.",
                "Container info updated for **{display_name}**": "Container-Info für **{display_name}** aktualisiert",
                "Text too long ({length}/250 characters). Please shorten it.": "Text zu lang ({length}/250 Zeichen). Bitte kürzen Sie ihn.",
                "Error displaying container info. Please try again.": "Fehler beim Anzeigen der Container-Informationen. Bitte versuchen Sie es erneut.",
                "Error saving container info. Please try again.": "Fehler beim Speichern der Container-Informationen. Bitte versuchen Sie es erneut.",
                
                # New /info command translations
                "This channel doesn't have permission to use the info command.": "Dieser Kanal hat keine Berechtigung, den Info-Befehl zu verwenden.",
                "This channel needs either status or control permissions to use the info command.": "Dieser Kanal benötigt entweder Status- oder Kontroll-Berechtigungen, um den Info-Befehl zu verwenden.",
                "Container '{}' not found in configuration.": "Container '{}' nicht in der Konfiguration gefunden.",
                "No additional information is configured for container '{}'.": "Keine zusätzlichen Informationen sind für Container '{}' konfiguriert.",
                "An error occurred while retrieving container information. Please try again later.": "Ein Fehler ist beim Abrufen der Container-Informationen aufgetreten. Bitte versuchen Sie es später erneut.",
                "Use `/info <servername>` to get detailed information about containers with ℹ️ indicators.": "Verwenden Sie `/info <servername>` um detaillierte Informationen über Container mit ℹ️ Indikatoren zu erhalten.",
                
                # Info Edit Modal translations
                "📝 Info Text": "📝 Info-Text",
                "🌐 IP/URL": "🌐 IP/URL",
                "☑️ Enable Info Button": "☑️ Info-Button aktivieren",
                "🌐 Show IP Address": "🌐 IP-Adresse anzeigen",
                "Example: Password: mypass123\nMax Players: 8\nMods: ModPack1, ModPack2": "Beispiel: Passwort: mypass123\nMax. Spieler: 8\nMods: ModPack1, ModPack2",
                "mydomain.com:7777 or 192.168.1.100:8080": "meinedomain.de:7777 oder 192.168.1.100:8080",
                "Type 'x' to enable, leave empty to disable": "Tippe 'x' zum Aktivieren, leer lassen zum Deaktivieren",
                "Type 'x' to show IP, leave empty to hide": "Tippe 'x' um IP anzuzeigen, leer lassen zum Verstecken",
                "mydomain.com or 192.168.1.100": "meinedomain.de oder 192.168.1.100",
                "🔌 Port": "🔌 Port",
                "8080": "8080",
                "❌ Port must contain only numbers.": "❌ Port darf nur Zahlen enthalten.",
                "❌ Port must be between 1 and 65535.": "❌ Port muss zwischen 1 und 65535 liegen.",
                
                # Spam Protection translations
                "Spam Protection Settings": "Spam-Schutz Einstellungen",
                "Configure rate limiting to prevent spam and abuse of bot commands.": "Konfigurieren Sie Rate-Limiting, um Spam und Missbrauch von Bot-Befehlen zu verhindern.",
                "Global Settings": "Globale Einstellungen",
                "Enable Spam Protection": "Spam-Schutz aktivieren",
                "Show Cooldown Messages": "Cooldown-Nachrichten anzeigen",
                "Log Rate Limit Violations": "Rate-Limit-Verstöße protokollieren",
                "Max Commands/Minute": "Max. Befehle/Minute",
                "Max Button Clicks/Minute": "Max. Button-Klicks/Minute",
                "Per user limit": "Pro Benutzer Limit",
                "Command Cooldowns (seconds)": "Befehl-Cooldowns (Sekunden)",
                "Button Cooldowns (seconds)": "Button-Cooldowns (Sekunden)",
                "Start Button": "Start-Button",
                "Stop Button": "Stop-Button",
                "Restart Button": "Neustart-Button",
                "Info Button": "Info-Button",
                "Refresh Button": "Aktualisieren-Button",
                "Spam protection settings saved successfully!": "Spam-Schutz Einstellungen erfolgreich gespeichert!",
                "Failed to save container info. Please try again.": "Container-Informationen konnten nicht gespeichert werden. Bitte versuchen Sie es erneut.",
                # Update notifications
                "DockerDiscordControl Update": "DockerDiscordControl Update",
                "New features available!": "Neue Features verfügbar!",
                "Spam Protection System": "Spam Protection System",
                "Container Info System": "Container-Info System",
                "Dynamic Timezone System": "Dynamisches Timezone System",
                "Configuration": "Konfiguration",
                "This message is only shown once": "Diese Nachricht wird nur einmal angezeigt",
                # Donation messages
                "Show donation information to support the project": "Spenden-Informationen zur Projektunterstützung anzeigen",
                "An error occurred while showing donation information. Please try again later.": "Fehler beim Anzeigen der Spenden-Informationen. Bitte versuchen Sie es später erneut.",
                "Support DockerDiscordControl": "Unterstütze DockerDiscordControl",
                "Hello! If you like DockerDiscordControl and want to support the development, I would be very happy about a small donation!": "Hallo! Falls dir DockerDiscordControl gefällt und du die Entwicklung unterstützen möchtest, würde ich mich über eine kleine Spende sehr freuen! Alles Liebe, MAX",
                "Thank you for your interest!": "Vielen Dank für dein Interesse!",
                "Every support helps to further develop and improve DockerDiscordControl!": "Jede Unterstützung hilft dabei, DockerDiscordControl weiterzuentwickeln und zu verbessern!",
                "Buy me a Coffee": "Buy me a Coffee",
                "Click here for Buy me a Coffee": "Klick hier für Buy me a Coffee",
                "Click here for PayPal": "Klick hier für PayPal",
                "Donations help with": "Spenden helfen bei:",
                "Server and hosting costs": "Server- und Hosting-Kosten",
                "Development time for new features": "Entwicklungszeit für neue Features", 
                "Bug fixes and support": "Bug-Fixes und Support",
                "Documentation improvements": "Verbesserung der Dokumentation",
                "This message is only shown every 2nd Sunday of the month": "Diese Nachricht wird nur jeden 2. Sonntag im Monat gepostet",
                # New donation broadcast translations
                "If DDC helps you, please consider supporting ongoing development. Donations help cover hosting, CI, maintenance, and feature work.": "Mit deiner Spende hilfst du nicht nur bei Hosting, CI, Wartung und Feature-Entwicklung – du füllst auch die Donation Engine und treibst unseren Community-Mech durch seine Evolutionsstufen.\n\nJede Spende = mehr Fuel → der Mech entwickelt sich weiter.",
                "Choose your preferred method:": "Wähle deine bevorzugte Methode:",
                "Click one of the buttons below to support DDC development": "Klicke auf eine der Schaltflächen unten, um die DDC-Entwicklung zu unterstützen und gleichzeitig den Mech zu powern.",
                "☕ Buy Me a Coffee": "☕ Buy Me a Coffee",
                "💳 PayPal": "💳 PayPal",
                "📢 Broadcast Donation": "📢 Spende erfassen",
                "📢 Broadcast Your Donation": "Erfasse deine Spende",
                "Your donation supports DDC and fuels the Donation Engine": "Deine Spende unterstützt DDC und füllt die Donation Engine – mehr Fuel = mehr Mech-Evolution.",
                "Your Name": "Dein Name",
                "How should we display your name?": "Wie sollen wir deinen Namen anzeigen?",
                "Donation Amount (optional)": "Spendenbetrag (optional)",
                "💰 Donation Amount (optional)": "💰 Spendenbetrag (optional)",
                "Numbers only, $ will be added automatically": "Nur Zahlen, $ wird automatisch hinzugefügt",
                "Share donation publicly?": "📢 Spende veröffentlichen?",
                "Remove X to keep private": "X entfernen um privat zu halten",
                "Cancel": "Abbrechen",
                "Submit": "Absenden",
                "e.g. 5 Euro, $10, etc. (leave empty if you prefer not to share)": "z.B. 5 Euro, $10, etc. (leer lassen, wenn nicht teilen möchten)",
                "10.50 (numbers only, $ will be added automatically)": "10.50 (Nur Zahlen, $ wird automatisch hinzugefügt)",
                "💝 Donation received": "💝 Spende erhalten",
                "{donor_name} supports DDC with {amount} – thank you so much ❤️": "{donor_name} unterstützt DDC mit {amount} – herzlichen Dank dafür ❤️",
                "{donor_name} supports DDC – thank you so much ❤️": "{donor_name} unterstützt DDC – herzlichen Dank dafür ❤️",
                "✅ **Donation broadcast sent!**": "✅ **Spendenankündigung gesendet!**",
                "📢 Sent to **{count}** channels": "📢 An **{count}** Kanäle gesendet",
                "⚠️ Failed to send to {count} channels": "⚠️ Fehler beim Senden an {count} Kanäle",
                "Thank you **{donor_name}** for your generosity! 🙏": "Danke **{donor_name}** für deine Großzügigkeit! 🙏",
                "✅ **Donation recorded privately!**": "✅ **Spende privat erfasst!**",
                "Thank you **{donor_name}** for your generous support! 🙏": "Danke **{donor_name}** für deine großzügige Unterstützung! 🙏",
                "Your donation has been recorded and helps fuel the Donation Engine.": "Deine Spende wurde erfasst und hilft dabei, die Donation Engine zu füllen.",
                "❌ Error sending donation broadcast. Please try again later.": "❌ Fehler beim Senden der Spendenankündigung. Bitte später erneut versuchen.",
                "Thank you for your support!": "Vielen Dank für deine Unterstützung!",
                "DockerDiscordControl": "DockerDiscordSteuerung",
                "This command is not allowed in this channel.": "Dieser Befehl ist in diesem Kanal nicht erlaubt.",
                "Force update initiated. All status messages will be regenerated.": "Forciertes Update initiiert. Alle Statusnachrichten werden neu generiert.",
                "Tip: Use": "Tipp: Nutze",
                "to refresh all messages if needed.": "um bei Bedarf alle Nachrichten zu aktualisieren.",
                "Bot Language": "Bot-Sprache",
                "Channel": "Kanal",
                "No servers configured": "Keine Server konfiguriert",
                "No Docker containers are configured. Add servers in the web interface.": "Keine Docker-Container konfiguriert. Füge Server im Webinterface hinzu.",
                "Control panel for Docker containers": "Kontrollpanel für Docker-Container",
                "Server Status": "Server Status",
                "Container": "Container",
                "Actions": "Aktionen",
                "Start": "Starten",
                "Stop": "Stoppen",
                "Restart": "Neustart",
                "Language": "Sprache",
                "Bot language set to": "Bot-Sprache gesetzt auf",
                "Control Panel": "Kontrollpanel",
                "No containers found": "Keine Container gefunden",
                "Initiating forced update. New status messages will be sent.": "Initiiere erzwungenes Update. Neue Statusnachrichten werden gesendet.",
                "No channels found where status updates are allowed.": "Keine Kanäle gefunden, in denen Status-Updates erlaubt sind.",
                "No servers configured to update.": "Keine Server zum Aktualisieren konfiguriert.",
                "The server is currently offline.": "Der Server ist derzeit offline.",

                # Status texts
                "Status could not be retrieved.": "Status konnte nicht abgerufen werden.",
                "**Online**": "Online",
                "**Offline**": "Offline",
                "Loading": "Lade",
                "Status": "Status",
                "Performance": "Leistung",
                "CPU": "CPU",
                "RAM": "RAM",
                "Uptime": "Laufzeit",
                "Detailed status not allowed.": "Detail-Status nicht erlaubt.",
                "Last update": "Letztes Update",
                "collapse": "-",
                "expand": "+",

                # Force Update texts
                "All status messages will be regenerated.": "Alle Statusnachrichten werden neu generiert.",
                "Error while updating messages: {error}": "Fehler bei der Aktualisierung der Nachrichten: {error}",

                # Command Success/Failure
                "✅ Server Action Successful": "✅ Server-Aktion Erfolgreich",
                "❌ Server Action Failed": "❌ Server-Aktion Fehlgeschlagen",
                "Server **{server_name}** is being processed {action_process_text}.": "Server **{server_name}** wird {action_process_text}.",
                "Server **{server_name}** could not be processed {action_process_text}.": "Server **{server_name}** konnte nicht {action_process_text} werden.",
                "started_process": "gestartet",
                "stopped_process": "gestoppt",
                "restarted_process": "neu gestartet",
                "Docker command failed or timed out": "Docker-Befehl fehlgeschlagen oder Zeitüberschreitung",
                "Action": "Aktion",
                "Executed by": "Ausgeführt von",
                "Error": "Fehler",
                "Docker container: {docker_name}": "Docker Container: {docker_name}",
                "Pending..." : "Wird verarbeitet...",
                "Status is currently unknown.": "Status ist derzeit unbekannt.",

                # Schedule Command Texts
                "This command can only be used in server channels.": "Dieser Befehl kann nur in Server-Kanälen verwendet werden.",
                "You do not have permission to use schedule commands in this channel.": "Du hast keine Berechtigung, Schedule-Befehle in diesem Kanal zu verwenden.",
                "Invalid time format. Please use HH:MM or e.g., 2:30pm.": "Ungültiges Zeitformat. Bitte verwende HH:MM oder z.B. 14:30.",
                "Invalid year format. Please use YYYY format (e.g., 2025).": "Ungültiges Jahresformat. Bitte verwende das JJJJ-Format (z.B. 2025).",
                "Invalid month format. Please use month name (e.g., January) or number (1-12).": "Ungültiges Monatsformat. Bitte verwende den Monatsnamen (z.B. Januar) oder eine Zahl (1-12).",
                "Day must be between 1 and 31.": "Der Tag muss zwischen 1 und 31 liegen.",
                "Invalid day format. Please use a number (1-31).": "Ungültiges Tagesformat. Bitte verwende eine Zahl (1-31).",
                "Cannot schedule task: The calculated execution time is invalid (e.g., in the past).": "Aufgabe kann nicht geplant werden: Die berechnete Ausführungszeit ist ungültig (z.B. in der Vergangenheit).",
                "Cannot schedule task: It conflicts with an existing task for the same container within a 10-minute window.": "Aufgabe kann nicht geplant werden: Sie steht in Konflikt mit einer bestehenden Aufgabe für denselben Container innerhalb eines 10-Minuten-Fensters.",
                "Task for {container_name} scheduled for {next_run_formatted}.": "Aufgabe für {container_name} geplant für {next_run_formatted}.",
                "Failed to schedule task. It might conflict with an existing task (time collision) or another error occurred.": "Fehler beim Planen der Aufgabe. Möglicherweise ein Konflikt mit einer bestehenden Aufgabe (Zeitkollision) oder ein anderer Fehler ist aufgetreten.",
                "An error occurred: {error}": "Ein Fehler ist aufgetreten: {error}",
                "Failed to schedule task. Possible time collision or other error.": "Fehler beim Planen der Aufgabe. Mögliche Zeitkollision oder anderer Fehler.",
                "Invalid weekday format. Please use a weekday name like 'Monday' or 'Montag'.": "Ungültiges Wochentagsformat. Bitte verwende einen Wochentagsnamen wie 'Monday' oder 'Montag'.",
                "Task for {container_name} scheduled weekly on {weekday_name} at {hour:02d}:{minute:02d}.": "Aufgabe für {container_name} wöchentlich geplant am {weekday_name} um {hour:02d}:{minute:02d}.",
                "Cannot schedule task: Invalid parameters or past execution time.": "Aufgabe kann nicht geplant werden: Ungültige Parameter oder vergangene Ausführungszeit.",
                "Cannot schedule task: Conflicts with an existing task within 10 minutes.": "Aufgabe kann nicht geplant werden: Konflikte mit einer bestehenden Aufgabe innerhalb von 10 Minuten.",
                "Task for {container_name} scheduled monthly on day {day} at {hour:02d}:{minute:02d}.": "Aufgabe für {container_name} monatlich geplant am Tag {day} um {hour:02d}:{minute:02d}.",
                "DockerDiscordControl - Scheduling Commands": "DockerDiscordSteuerung - Planungsbefehle",
                "Specialized commands are available for different scheduling cycles:": "Spezialisierte Befehle sind für verschiedene Planungszyklen verfügbar:",
                "Schedule a **one-time** task with year, month, day, and time.": "Plane eine **einmalige** Aufgabe mit Jahr, Monat, Tag und Uhrzeit.",
                "Schedule a **daily** task at the specified time.": "Plane eine **tägliche** Aufgabe zur angegebenen Zeit.",
                "Schedule a **weekly** task on the specified weekday and time.": "Plane eine **wöchentliche** Aufgabe am angegebenen Wochentag und zur angegebenen Zeit.",
                "Schedule a **monthly** task on the specified day and time.": "Plane eine **monatliche** Aufgabe am angegebenen Tag und zur angegebenen Zeit.",
                "Schedule a **yearly** task on the specified month, day, and time.": "Plane eine **jährliche** Aufgabe im angegebenen Monat, am angegebenen Tag und zur angegebenen Zeit.",
                "Task for {container_name} scheduled yearly on {month_name} {day} at {hour:02d}:{minute:02d}.": "Aufgabe für {container_name} jährlich geplant am {month_name} {day} um {hour:02d}:{minute:02d}.",
                "Next execution: {time}": "Nächste Ausführung: {time}",
                "No next execution time scheduled": "Keine nächste Ausführungszeit geplant",
                "Cycle": "Zyklus",

                # Weekday translations
                "Monday": "Montag",
                "Tuesday": "Dienstag",
                "Wednesday": "Mittwoch",
                "Thursday": "Donnerstag",
                "Friday": "Freitag",
                "Saturday": "Samstag",
                "Sunday": "Sonntag",
                "monday": "montag",
                "tuesday": "dienstag",
                "wednesday": "mittwoch",
                "thursday": "donnerstag",
                "friday": "freitag",
                "saturday": "samstag",
                "sunday": "sonntag",

                # Month translations
                "January": "Januar",
                "February": "Februar",
                "March": "März",
                "April": "April",
                "May": "Mai",
                "June": "Juni",
                "July": "Juli",
                "August": "August",
                "September": "September",
                "October": "Oktober",
                "November": "November",
                "December": "Dezember",

                "Only showing the next {count} tasks. Use the Web UI to view all.": "Es werden nur die nächsten {count} Aufgaben angezeigt. Verwende die Web-UI, um alle anzuzeigen.",
                "You don't have permission to schedule tasks for '{container}'.": "Du hast keine Berechtigung, Aufgaben für '{container}' zu planen.",
                "Note on Day Selection": "Hinweis zur Tagesauswahl",
                "Due to Discord's 25-option limit for autocomplete, only a strategic selection of days (1-5, 7, 9, 10, 12-15, 17, 18, 20-22, 24-28, 30, 31) is shown initially. You can still type any day number manually.": "Aufgrund von Discords 25-Optionen-Limit für Autovervollständigung wird anfänglich nur eine strategische Auswahl von Tagen (1-5, 7, 9, 10, 12-15, 17, 18, 20-22, 24-28, 30, 31) angezeigt. Du kannst trotzdem manuell jede Tageszahl eingeben.",
                "Shows information about all scheduled tasks.": "Zeigt Informationen zu allen geplanten Aufgaben an.",
                
                # Container Info Modal translations (German)
                "📝 Info Text": "📝 Info Text",
                "☑️ Enable Info Button": "☑️ Info-Button aktivieren",
                "Type 'x' to enable, leave empty to disable": "'x' eingeben zum Aktivieren, leer lassen zum Deaktivieren",
                "🌐 Show IP Address": "🌐 IP-Adresse anzeigen",
                "Type 'x' to show IP, leave empty to hide": "'x' eingeben um IP zu zeigen, leer lassen zum Verstecken",
                "📝 Custom Info Text (250 chars max)": "📝 Benutzerdefinierter Info-Text (max. 250 Zeichen)",
                "Example: Password: mypass123\\nMax Players: 8\\nMods: ModPack1, ModPack2": "Beispiel: Passwort: mypass123\\nMax. Spieler: 8\\nMods: ModPack1, ModPack2",
                "🌐 IP/URL": "🌐 IP/URL",
                "🌐 Custom IP/URL (optional)": "🌐 Benutzerdefinierte IP/URL (optional)",
                "mydomain.com:7777 or 192.168.1.100:8080": "mydomain.com:7777 oder 192.168.1.100:8080",
                "Currently: {status}, IP {ip_status}": "Aktuell: {status}, IP {ip_status}",
                "enabled": "aktiviert",
                "disabled": "deaktiviert", 
                "shown": "angezeigt",
                "hidden": "versteckt",
                "⚙️ Settings": "⚙️ Einstellungen",
                "Settings": "Einstellungen",
                "Type: enabled, show_ip (or leave empty to turn off both)": "Eingabe: enabled, show_ip (oder leer lassen, um beides zu deaktivieren)",
                "❌ Custom text too long ({length}/250 characters). Please shorten it.": "❌ Benutzerdefinierter Text zu lang ({length}/250 Zeichen). Bitte kürzen.",
                "\\n⚠️ IP format might be invalid: `{ip}`": "\\n⚠️ IP-Format könnte ungültig sein: `{ip}`",
                "✅ Container Info Updated": "✅ Container-Info aktualisiert",
                "Successfully updated information for **{name}**": "Informationen für **{name}** erfolgreich aktualisiert",
                "📝 Custom Text ({count}/250 chars)": "📝 Benutzerdefinierter Text ({count}/250 Zeichen)",
                "🌐 Custom IP/URL": "🌐 Benutzerdefinierte IP/URL",
                "✅ Info button enabled": "✅ Info-Button aktiviert",
                "❌ Info button disabled": "❌ Info-Button deaktiviert",
                "🌐 Show IP address": "🌐 IP-Adresse anzeigen",
                "🔒 Hide IP address": "🔒 IP-Adresse verstecken",
                "⚙️ Settings": "⚙️ Einstellungen",
                "❌ Failed to save container info for **{name}**. Please try again.": "❌ Container-Info für **{name}** konnte nicht gespeichert werden. Bitte erneut versuchen.",
                "❌ Failed to save container info for **{name}**. Check permissions on config directory.": "❌ Fehler beim Speichern für **{name}**. Prüfe Berechtigungen im config-Verzeichnis.",
                "❌ An error occurred while saving container info: {error}": "❌ Fehler beim Speichern der Container-Info: {error}",
                "❌ An error occurred while saving container info. Please try again.": "❌ Fehler beim Speichern der Container-Info. Bitte erneut versuchen.",
                
                # Mech System translations (German)
                "Mech-onate": "Mech-oniere",
                "Donation Engine": "Donation Engine",
                "Click + to view Mech details": "Klicke auf +, um die Mech-Details zu sehen",
                "Mech Status": "Mech Status",
                "Evolution": "Evolution",
                "Level": "Level",
                "Speed": "Geschwindigkeit", 
                "Fuel": "Treibstoff",
                "Fuel Consumption": "Treibstoffverbrauch",
                "Glvl": "Glvl",
                "Fuel/Donate": "Mit Spende auftanken",
                "Evolution level up - updating mech animation": "Evolution Level-Up - Mech Animation wird aktualisiert",
                "Donation received - updating status": "Spende erhalten - Status wird aktualisiert",
                "Donation recorded - updating fuel status": "Spende erfasst - Fuel-Status wird aktualisiert",
                "MECH EVOLUTION ACHIEVED!": "MECH EVOLUTION ERREICHT!",
                "Your Mech has ascended to the next evolution stage: {evolution_name}": "Ihr Mech ist zur nächsten Evolutionsstufe aufgestiegen: {evolution_name}",
                "The fuel system has been reset and refueled with the remaining surplus of ${surplus:.2f}.": "Das Fuel-System wurde zurückgesetzt und mit dem verbliebenen Überschuss von ${surplus:.2f} aufgetankt.",
                "Significant Glvl change detected": "Signifikante Glvl-Änderung erkannt",
                "Upgrading to force_recreate=True due to significant Glvl change": "Upgrade auf force_recreate=True aufgrund signifikanter Glvl-Änderung",
                
                # Evolution Names (German)
                "SCRAP MECH": "SCHROTT MECH",
                "REPAIRED MECH": "REPARIERTER MECH", 
                "STANDARD MECH": "STANDARD MECH",
                "ENHANCED MECH": "VERSTÄRKTER MECH",
                "ADVANCED MECH": "FORTGESCHRITTENER MECH",
                "ELITE MECH": "ELITE MECH",
                "CYBER MECH": "CYBER MECH",
                "PLASMA MECH": "PLASMA MECH",
                "QUANTUM MECH": "QUANTUM MECH", 
                "DIVINE MECH": "GÖTTLICHER MECH",
                "OMEGA MECH": "OMEGA MECH",
                "MAX EVOLUTION REACHED!": "MAXIMALE EVOLUTION ERREICHT!",
                
                # Period texts for schedule_info
                "all": "alle",
                "next_week": "nächste_woche",
                "next_month": "nächster_monat",
                "today": "heute",
                "tomorrow": "morgen",
                "next_day": "nächster_tag",
                "Scheduled tasks for the next 24 hours": "Geplante Aufgaben für die nächsten 24 Stunden",
                "Scheduled tasks for the next week": "Geplante Aufgaben für die nächste Woche",
                "Scheduled tasks for the next month": "Geplante Aufgaben für den nächsten Monat",
                "All active scheduled tasks": "Alle aktiven geplanten Aufgaben",
                "No active scheduled tasks found for the specified criteria.": "Keine aktiven geplanten Aufgaben für die angegebenen Kriterien gefunden.",
                "No active scheduled tasks found for the specified period.": "Keine aktiven geplanten Aufgaben für den angegebenen Zeitraum gefunden.",
                "All tasks have been marked as expired or inactive.": "Alle Aufgaben wurden als abgelaufen oder inaktiv markiert.",
                "An error occurred while fetching scheduled tasks. Please check the logs.": "Beim Abrufen der geplanten Aufgaben ist ein Fehler aufgetreten. Bitte überprüfe die Logs.",
                
                # Task descriptions
                "Weekly {action} on {weekday_name} at {hour:02d}:{minute:02d}": "Wöchentliches {action} am {weekday_name} um {hour:02d}:{minute:02d}",

                # Ping Command
                "Pong! Latency: {latency:.2f} ms": "Pong! Latenz: {latency:.2f} ms",
                
                # Help Command
                "DockerDiscordControl - Help": "DockerDiscordControl - Hilfe",
                "Here are the available commands:": "Hier sind die verfügbaren Befehle:",
                "Displays the status of all configured Docker containers.": "Zeigt den Status aller konfigurierten Docker-Container an.",
                "Controls a specific Docker container. Actions: `start`, `stop`, `restart`. Requires permissions.": "Steuert einen bestimmten Docker-Container. Aktionen: `start`, `stop`, `restart`. Erfordert Berechtigungen.",
                "(Re)generates the main control panel message in channels configured for it.": "Generiert die Hauptkontrollpanel-Nachricht in Kanälen, die dafür konfiguriert sind, (neu).",
                "Shows this help message.": "Zeigt diese Hilfemeldung an.",
                "Checks the bot's latency.": "Überprüft die Latenz des Bots.",

                # Heartbeat
                "❤️ Heartbeat signal at {timestamp}": "❤️ Herzschlagsignal um {timestamp}",

                # Command descriptions
                "Shows the status of all containers": "Zeigt den Status aller Container an",
                "Shortcut: Shows the status of all containers": "Kurzbefehl: Zeigt den Status aller Container an",
                "Displays help for available commands": "Zeigt Hilfe für verfügbare Befehle an",
                "Shows the bot's latency": "Zeigt die Latenz des Bots an",
                "Displays the control panel in the control channel": "Zeigt das Kontrollpanel im Kontrollkanal an",

                # Schedule command descriptions
                "Schedule a one-time task": "Plant eine einmalige Aufgabe",
                "Schedule a daily task": "Plant eine tägliche Aufgabe",
                "Schedule a weekly task": "Plant eine wöchentliche Aufgabe",
                "Schedule a monthly task": "Plant eine monatliche Aufgabe",
                "Schedule a yearly task": "Plant eine jährliche Aufgabe",
                "Shows schedule command help": "Zeigt Hilfe zu Planungsbefehlen an",
                "Shows information about scheduled tasks": "Zeigt Informationen über geplante Aufgaben an",

                # Command parameter descriptions
                "The Docker container to schedule": "Der zu planende Docker-Container",
                "Action to perform": "Auszuführende Aktion",
                "Time in HH:MM format (e.g., 14:30)": "Zeit im HH:MM-Format (z.B. 14:30)",
                "Time in HH:MM format (e.g., 08:00)": "Zeit im HH:MM-Format (z.B. 08:00)",
                "Time in HH:MM format": "Zeit im HH:MM-Format",
                "Day of month (e.g., 15)": "Tag des Monats (z.B. 15)",
                "Month (e.g., 07 or July)": "Monat (z.B. 07 oder Juli)",
                "Year (e.g., 2024)": "Jahr (z.B. 2024)",
                "Day of the week (e.g., Monday or 1)": "Wochentag (z.B. Montag oder 1)",
                "Day of the month (1-31)": "Tag des Monats (1-31)",
                "Container name (or 'all')": "Container-Name (oder 'all')",
                "Time period (e.g., next_week)": "Zeitraum (z.B. next_week)",
                "Task ID to delete": "Zu löschende Task-ID",

                # Task Delete Panel texts
                "Task Delete Panel": "Task-Löschpanel",
                "Click any button below to delete the corresponding task:": "Klicke einen der Buttons unten, um die entsprechende Aufgabe zu löschen:",
                "Legend:** O = Once, D = Daily, W = Weekly, M = Monthly, Y = Yearly": "Legende:** O = Einmalig, D = Täglich, W = Wöchentlich, M = Monatlich, Y = Jährlich",
                "Showing first 25 of {total} tasks": "Zeige erste 25 von {total} Aufgaben",
                "Found {total} active tasks": "{total} aktive Aufgaben gefunden",
                "You do not have permission to delete tasks in this channel.": "Du hast keine Berechtigung, Aufgaben in diesem Kanal zu löschen.",
                "✅ Successfully deleted scheduled task!\n**Task ID:** {task_id}\n**Container:** {container}\n**Action:** {action}\n**Cycle:** {cycle}": "✅ Geplante Aufgabe erfolgreich gelöscht!\n**Task-ID:** {task_id}\n**Container:** {container}\n**Aktion:** {action}\n**Zyklus:** {cycle}",

                # Updated task command descriptions
                "Shows task command help": "Zeigt Task-Befehl-Hilfe an",
                "Delete a scheduled task": "Lösche eine geplante Aufgabe",
                "Delete a scheduled task by its task ID.": "Lösche eine geplante Aufgabe anhand ihrer Task-ID.",
                "Show active tasks with delete buttons": "Zeige aktive Aufgaben mit Lösch-Buttons",

                # Task command names (updated from schedule to task)
                "Schedule a one-time task": "Plane eine einmalige Aufgabe",
                "Schedule a daily task": "Plane eine tägliche Aufgabe", 
                "Schedule a weekly task": "Plane eine wöchentliche Aufgabe",
                "Schedule a monthly task": "Plane eine monatliche Aufgabe",
                "Schedule a yearly task": "Plane eine jährliche Aufgabe",

                # Live Logs translations
                "🔄 Refreshing logs...": "🔄 Logs werden aktualisiert...",
                "⏳ Updating...": "⏳ Wird aktualisiert...",
                "❌ Live Logs feature is currently disabled by administrator.": "❌ Live Logs Funktion ist derzeit vom Administrator deaktiviert.",
                "https://ddc.bot • Click ▶️ to start live updates": "https://ddc.bot • Klicken Sie ▶️ um Live-Updates zu starten",

                # Error messages
                "Error during execution: {error}": "Fehler bei der Ausführung: {error}",
            },

            # French
            'fr': {
                 # General texts
                "Docker Control Panel": "Panneau de contrôle Docker",
                "Here you can control your Docker containers. Use the buttons below each server to perform actions.":
                    "Ici, vous pouvez contrôler vos conteneurs Docker. Utilisez les boutons sous chaque serveur pour effectuer des actions.",
                "Available Commands": "Commandes disponibles",
                "Shows this control panel": "Affiche ce panneau de contrôle",
                "Shows server status (shortcut: /ss)": "Affiche l'état du serveur (raccourci: /ss)",
                "Directly control a container": "Contrôle directement un conteneur",
                "Shows help about available commands": "Affiche l'aide sur les commandes disponibles",
                "Shows the bot response time": "Affiche le temps de réponse du bot",
                "Edit container information": "Modifier les informations du conteneur",
                "Container info is not configured for this container.": "Les informations du conteneur ne sont pas configurées pour ce conteneur.",
                "Container info is not enabled for **{display_name}**. Enable it in the web UI first.": "Les informations du conteneur ne sont pas activées pour **{display_name}**. Activez-les d'abord dans l'interface web.",
                "You don't have permission to view container info in this channel.": "Vous n'avez pas la permission de voir les informations du conteneur dans ce canal.",
                "You do not have permission to edit container info in this channel.": "Vous n'avez pas la permission de modifier les informations du conteneur dans ce canal.",
                "Container information is read-only in this channel.": "Les informations du conteneur sont en lecture seule dans ce canal.",
                "Container info updated for **{display_name}**": "Informations du conteneur mises à jour pour **{display_name}**",
                "Text too long ({length}/250 characters). Please shorten it.": "Texte trop long ({length}/250 caractères). Veuillez le raccourcir.",
                "Error displaying container info. Please try again.": "Erreur lors de l'affichage des informations du conteneur. Veuillez réessayer.",
                "Error saving container info. Please try again.": "Erreur lors de la sauvegarde des informations du conteneur. Veuillez réessayer.",
                "Failed to save container info. Please try again.": "Échec de la sauvegarde des informations du conteneur. Veuillez réessayer.",
                "DockerDiscordControl": "ContrôleDiscordDocker",
                "This command is not allowed in this channel.": "Cette commande n'est pas autorisée dans ce canal.",
                "Force update initiated. All status messages will be regenerated.": "Mise à jour forcée initiée. Tous les messages d'état seront régénérés.",
                "Tip: Use": "Conseil: Utilisez",
                "to refresh all messages if needed.": "pour rafraîchir tous les messages si nécessaire.",
                "Bot Language": "Langue du bot",
                "Channel": "Canal",
                "No servers configured": "Aucun serveur configuré",
                "No Docker containers are configured. Add servers in the web interface.": "Aucun conteneur Docker n'est configuré. Ajoutez des serveurs dans l'interface web.",
                "Control panel for Docker containers": "Panneau de contrôle pour les conteneurs Docker",
                "Server Status": "État du serveur",
                "Container": "Conteneur",
                "Actions": "Actions",
                "Start": "Démarrer",
                "Stop": "Arrêter",
                "Restart": "Redémarrer",
                "Language": "Langue",
                "Bot language set to": "Langue du bot définie sur",
                "Control Panel": "Panneau de contrôle",
                "No containers found": "Aucun conteneur trouvé",
                "Initiating forced update. New status messages will be sent.": "Initiation de la mise à jour forcée. De nouveaux messages d'état seront envoyés.",
                "No channels found where status updates are allowed.": "Aucun canal trouvé où les mises à jour de statut sont autorisées.",
                "No servers configured to update.": "Aucun serveur configuré pour la mise à jour.",
                "The server is currently offline.": "Le serveur est actuellement hors ligne.",


                # Status texts
                "Status could not be retrieved.": "Impossible de récupérer l'état.",
                "**Online**": "En ligne",
                "**Offline**": "Hors ligne",
                "Loading": "Chargement",
                "Status": "État",
                "Performance": "Performance",
                "CPU": "CPU",
                "RAM": "RAM",
                "Uptime": "Temps de fonctionnement",
                "Detailed status not allowed.": "État détaillé non autorisé.",
                "Last update": "Dernière mise à jour",
                "collapse": "-",
                "expand": "+",


                # Force Update texts
                "All status messages will be regenerated.": "Tous les messages d'état seront régénérés.",
                "Error while updating messages: {error}": "Erreur lors de la mise à jour des messages : {error}",
                "This command is not allowed in this channel": "Cette commande n'est pas autorisée dans ce canal",

                # Command Success/Failure (French)
                "✅ Server Action Successful": "✅ Action sur le serveur réussie",
                "❌ Server Action Failed": "❌ Échec de l'action sur le serveur",
                "Server **{server_name}** is being processed {action_process_text}.": "Le serveur **{server_name}** est en cours de {action_process_text}.", # Needs french grammar check
                "Server **{server_name}** could not be processed {action_process_text}.": "Le serveur **{server_name}** n'a pas pu être {action_process_text}.", # Needs french grammar check
                "started_process": "démarré",
                "stopped_process": "arrêté",
                "restarted_process": "redémarré",
                "Docker command failed or timed out": "La commande Docker a échoué ou a expiré",
                "Action": "Action",
                "Executed by": "Exécuté par",
                "Error": "Erreur",
                "Docker container: {docker_name}": "Conteneur Docker : {docker_name}",
                "Pending..." : "En cours...",
                "Status is currently unknown.": "Statut actuellement inconnu.",

                # Schedule Command Texts
                "This command can only be used in server channels.": "Cette commande ne peut être utilisée que dans les canaux du serveur.",
                "You do not have permission to use schedule commands in this channel.": "Vous n'avez pas la permission d'utiliser les commandes de planification dans ce canal.",
                "Invalid time format. Please use HH:MM or e.g., 2:30pm.": "Format d'heure invalide. Veuillez utiliser HH:MM ou par ex. 14h30.",
                "Invalid year format. Please use YYYY format (e.g., 2025).": "Format d'année invalide. Veuillez utiliser le format AAAA (par ex. 2025).",
                "Invalid month format. Please use month name (e.g., January) or number (1-12).": "Format de mois invalide. Veuillez utiliser le nom du mois (par ex. Janvier) ou un nombre (1-12).",
                "Day must be between 1 and 31.": "Le jour doit être compris entre 1 et 31.",
                "Invalid day format. Please use a number (1-31).": "Format de jour invalide. Veuillez utiliser un nombre (1-31).",
                "Cannot schedule task: The calculated execution time is invalid (e.g., in the past).": "Impossible de planifier la tâche : l'heure d'exécution calculée est invalide (par ex. dans le passé).",
                "Cannot schedule task: It conflicts with an existing task for the same container within a 10-minute window.": "Impossible de planifier la tâche : elle est en conflit avec une tâche existante pour le même conteneur dans une fenêtre de 10 minutes.",
                "Task for {container_name} scheduled for {next_run_formatted}.": "Tâche pour {container_name} planifiée pour le {next_run_formatted}.",
                "Failed to schedule task. It might conflict with an existing task (time collision) or another error occurred.": "Échec de la planification de la tâche. Elle pourrait être en conflit avec une tâche existante (collision temporelle) ou une autre erreur s'est produite.",
                "An error occurred: {error}": "Une erreur s'est produite : {error}",
                "Failed to schedule task. Possible time collision or other error.": "Échec de la planification de la tâche. Collision temporelle possible ou autre erreur.",
                "Invalid weekday format. Please use a weekday name like 'Monday' or 'Montag'.": "Format de jour de la semaine invalide. Veuillez utiliser un nom de jour comme 'Monday' ou 'Lundi'.",
                "Task for {container_name} scheduled weekly on {weekday_name} at {hour:02d}:{minute:02d}.": "Tâche pour {container_name} planifiée hebdomadairement le {weekday_name} à {hour:02d}:{minute:02d}.",
                "Cannot schedule task: Invalid parameters or past execution time.": "Impossible de planifier la tâche : paramètres invalides ou heure d'exécution passée.",
                "Cannot schedule task: Conflicts with an existing task within 10 minutes.": "Impossible de planifier la tâche : conflits avec une tâche existante dans les 10 minutes.",
                "Task for {container_name} scheduled monthly on day {day} at {hour:02d}:{minute:02d}.": "Tâche pour {container_name} planifiée mensuellement le jour {day} à {hour:02d}:{minute:02d}.",
                "DockerDiscordControl - Scheduling Commands": "ContrôleDiscordDocker - Commandes de planification",
                "Specialized commands are available for different scheduling cycles:": "Des commandes spécialisées sont disponibles pour différents cycles de planification :",
                "Schedule a **one-time** task with year, month, day, and time.": "Planifiez une tâche **unique** avec l'année, le mois, le jour et l'heure.",
                "Schedule a **daily** task at the specified time.": "Planifiez une tâche **quotidienne** à l'heure spécifiée.",
                "Schedule a **weekly** task on the specified weekday and time.": "Planifiez une tâche **hebdomadaire** le jour de la semaine et à l'heure spécifiés.",
                "Schedule a **monthly** task on the specified day and time.": "Planifiez une tâche **mensuelle** le jour et à l'heure spécifiés.",
                "Schedule a **yearly** task on the specified month, day, and time.": "Planifiez une tâche **annuelle** le mois, le jour et à l'heure spécifiés.",
                "Task for {container_name} scheduled yearly on {month_name} {day} at {hour:02d}:{minute:02d}.": "Tâche pour {container_name} planifiée annuellement le {day} {month_name} à {hour:02d}:{minute:02d}.",
                "Next execution: {time}": "Prochaine exécution : {time}",
                "No next execution time scheduled": "Aucune prochaine exécution programmée",
                "Cycle": "Cycle",

                # Weekday translations
                "Monday": "Lundi",
                "Tuesday": "Mardi",
                "Wednesday": "Mercredi",
                "Thursday": "Jeudi",
                "Friday": "Vendredi",
                "Saturday": "Samedi",
                "Sunday": "Dimanche",
                "monday": "lundi",
                "tuesday": "mardi",
                "wednesday": "mercredi",
                "thursday": "jeudi",
                "friday": "vendredi",
                "saturday": "samedi",
                "sunday": "dimanche",

                # Month translations
                "January": "Janvier",
                "February": "Février",
                "March": "Mars",
                "April": "Avril",
                "May": "Mai",
                "June": "Juin",
                "July": "Juillet",
                "August": "Août",
                "September": "Septembre",
                "October": "Octobre",
                "November": "Novembre",
                "December": "Décembre",

                "Only showing the next {count} tasks. Use the Web UI to view all.": "Affichage des {count} prochaines tâches uniquement. Utilisez l'interface Web pour tout voir.",
                "You don't have permission to schedule tasks for '{container}'.": "Vous n'avez pas la permission de planifier des tâches pour '{container}'.",
                "Note on Day Selection": "Note sur la sélection de jour",
                "Due to Discord's 25-option limit for autocomplete, only a strategic selection of days (1-5, 7, 9, 10, 12-15, 17, 18, 20-22, 24-28, 30, 31) is shown initially. You can still type any day number manually.": "En raison de la limite de 25 options de Discord pour l'autocomplétion, seule une sélection stratégique de jours (1-5, 7, 9, 10, 12-15, 17, 18, 20-22, 24-28, 30, 31) est initialement affichée. Vous pouvez toujours taper manuellement n'importe quel numéro de jour.",
                "Shows information about all scheduled tasks.": "Affiche des informations sur toutes les tâches planifiées.",
                
                # Container Info Modal translations (French)
                "📝 Info Text": "📝 Texte d'info",
                "☑️ Enable Info Button": "☑️ Activer le bouton info",
                "Type 'x' to enable, leave empty to disable": "Tapez 'x' pour activer, laissez vide pour désactiver",
                "🌐 Show IP Address": "🌐 Afficher l'adresse IP",
                "Type 'x' to show IP, leave empty to hide": "Tapez 'x' pour afficher l'IP, laissez vide pour cacher",
                "📝 Custom Info Text (250 chars max)": "📝 Texte d'info personnalisé (250 caractères max)",
                "Example: Password: mypass123\\nMax Players: 8\\nMods: ModPack1, ModPack2": "Exemple: Mot de passe: mypass123\\nJoueurs max: 8\\nMods: ModPack1, ModPack2",
                "🌐 IP/URL": "🌐 IP/URL",
                "🌐 Custom IP/URL (optional)": "🌐 IP/URL personnalisée (optionnel)",
                "mydomain.com:7777 or 192.168.1.100:8080": "mydomain.com:7777 ou 192.168.1.100:8080",
                "Currently: {status}, IP {ip_status}": "Actuellement: {status}, IP {ip_status}",
                "enabled": "activé",
                "disabled": "désactivé", 
                "shown": "affiché",
                "hidden": "caché",
                "⚙️ Settings": "⚙️ Paramètres",
                "Settings": "Paramètres",
                "Type: enabled, show_ip (or leave empty to turn off both)": "Tapez: enabled, show_ip (ou laissez vide pour désactiver les deux)",
                "❌ Custom text too long ({length}/250 characters). Please shorten it.": "❌ Texte personnalisé trop long ({length}/250 caractères). Veuillez le raccourcir.",
                "\\n⚠️ IP format might be invalid: `{ip}`": "\\n⚠️ Le format IP pourrait être invalide: `{ip}`",
                "✅ Container Info Updated": "✅ Info du conteneur mise à jour",
                "Successfully updated information for **{name}**": "Informations mises à jour avec succès pour **{name}**",
                "📝 Custom Text ({count}/250 chars)": "📝 Texte personnalisé ({count}/250 caractères)",
                "🌐 Custom IP/URL": "🌐 IP/URL personnalisée",
                "✅ Info button enabled": "✅ Bouton info activé",
                "❌ Info button disabled": "❌ Bouton info désactivé",
                "🌐 Show IP address": "🌐 Afficher l'adresse IP",
                "🔒 Hide IP address": "🔒 Masquer l'adresse IP",
                "⚙️ Settings": "⚙️ Paramètres",
                "❌ Failed to save container info for **{name}**. Please try again.": "❌ Échec de la sauvegarde des infos pour **{name}**. Veuillez réessayer.",
                "❌ Failed to save container info for **{name}**. Check permissions on config directory.": "❌ Échec de sauvegarde pour **{name}**. Vérifiez les permissions du répertoire config.",
                "❌ An error occurred while saving container info: {error}": "❌ Erreur lors de la sauvegarde des infos du conteneur: {error}",
                "❌ An error occurred while saving container info. Please try again.": "❌ Une erreur s'est produite lors de la sauvegarde. Veuillez réessayer.",
                
                # Period texts for schedule_info
                "all": "tous",
                "next_week": "semaine_prochaine",
                "next_month": "mois_prochain",
                "today": "aujourd_hui",
                "tomorrow": "demain",
                "next_day": "jour_suivant",
                "Scheduled tasks for the next 24 hours": "Tâches planifiées pour les prochaines 24 heures",
                "Scheduled tasks for the next week": "Tâches planifiées pour la semaine prochaine",
                "Scheduled tasks for the next month": "Tâches planifiées pour le mois prochain",
                "All active scheduled tasks": "Toutes les tâches planifiées actives",
                "No active scheduled tasks found for the specified criteria.": "Aucune tâche planifiée active trouvée pour les critères spécifiés.",
                "No active scheduled tasks found for the specified period.": "Aucune tâche planifiée active trouvée pour la période spécifiée.",
                "All tasks have been marked as expired or inactive.": "Toutes les tâches ont été marquées comme expirées ou inactives.",
                "An error occurred while fetching scheduled tasks. Please check the logs.": "Une erreur s'est produite lors de la récupération des tâches planifiées. Veuillez consulter les journaux.",
                
                # Task descriptions
                "Weekly {action} on {weekday_name} at {hour:02d}:{minute:02d}": "Action {action} hebdomadaire le {weekday_name} à {hour:02d}:{minute:02d}",

                # Ping Command
                "Pong! Latency: {latency:.2f} ms": "Pong! Latence: {latency:.2f} ms",
                
                # Help Command
                "DockerDiscordControl - Help": "ContrôleDiscordDocker - Aide",
                "Here are the available commands:": "Voici les commandes disponibles:",
                "Displays the status of all configured Docker containers.": "Affiche l'état de tous les conteneurs Docker configurés.",
                "Controls a specific Docker container. Actions: `start`, `stop`, `restart`. Requires permissions.": "Contrôle un conteneur Docker spécifique. Actions: `start`, `stop`, `restart`. Nécessite des permissions.",
                "(Re)generates the main control panel message in channels configured for it.": "(Re)génère le message du panneau de contrôle principal dans les canaux configurés à cet effet.",
                "Shows this help message.": "Affiche ce message d'aide.",
                "Checks the bot's latency.": "Vérifie la latence du bot.",

                # Heartbeat
                "❤️ Heartbeat signal at {timestamp}": "❤️ Signal de pulsation à {timestamp}",

                # Command descriptions
                "Shows the status of all containers": "Affiche l'état de tous les conteneurs",
                "Shortcut: Shows the status of all containers": "Raccourci: Affiche l'état de tous les conteneurs",
                "Displays help for available commands": "Affiche l'aide pour les commandes disponibles",
                "Shows the bot's latency": "Affiche la latence du bot",
                "Displays the control panel in the control channel": "Affiche le panneau de contrôle dans le canal de contrôle",

                # Schedule command descriptions
                "Schedule a one-time task": "Planifier une tâche unique",
                "Schedule a daily task": "Planifier une tâche quotidienne",
                "Schedule a weekly task": "Planifier une tâche hebdomadaire",
                "Schedule a monthly task": "Planifier une tâche mensuelle",
                "Schedule a yearly task": "Planifier une tâche annuelle",
                "Shows schedule command help": "Affiche l'aide sur les commandes de planification",
                "Shows information about scheduled tasks": "Affiche des informations sur les tâches planifiées",

                # Command parameter descriptions
                "The Docker container to schedule": "Le conteneur Docker à planifier",
                "Action to perform": "Action à effectuer",
                "Time in HH:MM format (e.g., 14:30)": "Heure au format HH:MM (ex: 14:30)",
                "Time in HH:MM format (e.g., 08:00)": "Heure au format HH:MM (ex: 08:00)",
                "Time in HH:MM format": "Heure au format HH:MM",
                "Day of month (e.g., 15)": "Jour du mois (ex: 15)",
                "Month (e.g., 07 or July)": "Mois (ex: 07 ou Juillet)",
                "Year (e.g., 2024)": "Année (ex: 2024)",
                "Day of the week (e.g., Monday or 1)": "Jour de la semaine (ex: Lundi ou 1)",
                "Day of the month (1-31)": "Jour du mois (1-31)",
                "Container name (or 'all')": "Nom du conteneur (ou 'all')",
                "Time period (e.g., next_week)": "Période (ex: next_week)",
                "Task ID to delete": "ID de tâche à supprimer",

                # Task Delete Panel texts
                "Task Delete Panel": "Panneau de suppression de tâches",
                "Click any button below to delete the corresponding task:": "Cliquez sur un bouton ci-dessous pour supprimer la tâche correspondante:",
                "Legend:** O = Once, D = Daily, W = Weekly, M = Monthly, Y = Yearly": "Légende:** O = Une fois, D = Quotidien, W = Hebdomadaire, M = Mensuel, Y = Annuel",
                "Showing first 25 of {total} tasks": "Affichage des 25 premières tâches sur {total}",
                "Found {total} active tasks": "{total} tâches actives trouvées",
                "You do not have permission to delete tasks in this channel.": "Vous n'avez pas la permission de supprimer des tâches dans ce canal.",
                "✅ Successfully deleted scheduled task!\n**Task ID:** {task_id}\n**Container:** {container}\n**Action:** {action}\n**Cycle:** {cycle}": "✅ Tâche planifiée supprimée avec succès!\n**ID de tâche:** {task_id}\n**Conteneur:** {container}\n**Action:** {action}\n**Cycle:** {cycle}",

                # Updated task command descriptions
                "Shows task command help": "Affiche l'aide des commandes de tâches",
                "Delete a scheduled task": "Supprimer une tâche planifiée",
                "Delete a scheduled task by its task ID.": "Supprimer une tâche planifiée par son ID de tâche.",
                "Show active tasks with delete buttons": "Afficher les tâches actives avec boutons de suppression",

                # Task command names (updated from schedule to task)
                "Schedule a one-time task": "Plane une tâche unique",
                "Schedule a daily task": "Plane une tâche quotidienne", 
                "Schedule a weekly task": "Plane une tâche hebdomadaire",
                "Schedule a monthly task": "Plane une tâche mensuelle",
                "Schedule a yearly task": "Plane une tâche annuelle",

                # Live Logs translations
                "🔄 Refreshing logs...": "🔄 Actualisation des logs...",
                "⏳ Updating...": "⏳ Mise à jour...",
                "❌ Live Logs feature is currently disabled by administrator.": "❌ La fonctionnalité Live Logs est actuellement désactivée par l'administrateur.",
                "https://ddc.bot • Click ▶️ to start live updates": "https://ddc.bot • Cliquez ▶️ pour démarrer les mises à jour en direct",

                # Error messages
                "Error during execution: {error}": "Erreur pendant l'exécution: {error}",
                
                # New /info command translations
                "This channel doesn't have permission to use the info command.": "Ce canal n'a pas la permission d'utiliser la commande info.",
                "This channel needs either status or control permissions to use the info command.": "Ce canal nécessite des permissions de statut ou de contrôle pour utiliser la commande info.",
                "Container '{}' not found in configuration.": "Conteneur '{}' non trouvé dans la configuration.",
                "No additional information is configured for container '{}'.": "Aucune information supplémentaire n'est configurée pour le conteneur '{}'.",
                "An error occurred while retrieving container information. Please try again later.": "Une erreur s'est produite lors de la récupération des informations du conteneur. Veuillez réessayer plus tard.",
                "Use `/info <servername>` to get detailed information about containers with ℹ️ indicators.": "Utilisez `/info <nomserveur>` pour obtenir des informations détaillées sur les conteneurs avec indicateurs ℹ️.",
                
                # Info Edit Modal translations
                "📝 Info Text": "📝 Texte d'info",
                "🌐 IP/URL": "🌐 IP/URL",
                "☑️ Enable Info Button": "☑️ Activer le bouton info",
                "🌐 Show IP Address": "🌐 Afficher l'adresse IP",
                "Example: Password: mypass123\nMax Players: 8\nMods: ModPack1, ModPack2": "Exemple: Mot de passe: mypass123\nJoueurs max: 8\nMods: ModPack1, ModPack2",
                "mydomain.com:7777 or 192.168.1.100:8080": "mondomaine.fr:7777 ou 192.168.1.100:8080",
                "Type 'x' to enable, leave empty to disable": "Tapez 'x' pour activer, laissez vide pour désactiver",
                "Type 'x' to show IP, leave empty to hide": "Tapez 'x' pour afficher l'IP, laissez vide pour masquer",
                "mydomain.com or 192.168.1.100": "mondomaine.fr ou 192.168.1.100",
                "🔌 Port": "🔌 Port",
                "8080": "8080",
                "❌ Port must contain only numbers.": "❌ Le port ne doit contenir que des chiffres.",
                "❌ Port must be between 1 and 65535.": "❌ Le port doit être entre 1 et 65535.",
                
                # Spam Protection translations
                "Spam Protection Settings": "Paramètres de protection anti-spam",
                "Configure rate limiting to prevent spam and abuse of bot commands.": "Configurez la limitation de débit pour éviter le spam et l'abus des commandes du bot.",
                "Global Settings": "Paramètres globaux",
                "Enable Spam Protection": "Activer la protection anti-spam",
                "Show Cooldown Messages": "Afficher les messages de temps de recharge",
                "Log Rate Limit Violations": "Enregistrer les violations de limite de débit",
                "Max Commands/Minute": "Max. commandes/minute",
                "Max Button Clicks/Minute": "Max. clics de bouton/minute",
                "Per user limit": "Limite par utilisateur",
                "Command Cooldowns (seconds)": "Temps de recharge des commandes (secondes)",
                "Button Cooldowns (seconds)": "Temps de recharge des boutons (secondes)",
                "Start Button": "Bouton Démarrer",
                "Stop Button": "Bouton Arrêter",
                "Restart Button": "Bouton Redémarrer",
                "Info Button": "Bouton Info",
                "Refresh Button": "Bouton Actualiser",
                "Spam protection settings saved successfully!": "Paramètres de protection anti-spam enregistrés avec succès!",
                # Donation messages
                "Show donation information to support the project": "Afficher les informations de don pour soutenir le projet",
                "An error occurred while showing donation information. Please try again later.": "Une erreur s'est produite lors de l'affichage des informations de don. Veuillez réessayer plus tard.",
                "Support DockerDiscordControl": "Soutenir DockerDiscordControl",
                "Hello! If you like DockerDiscordControl and want to support the development, I would be very happy about a small donation!": "Salut ! Si vous aimez DockerDiscordControl et souhaitez soutenir le développement, je serais très heureux d'un petit don ! Toute mon affection, MAX",
                "Thank you for your interest!": "Merci pour votre intérêt !",
                "Every support helps to further develop and improve DockerDiscordControl!": "Chaque soutien aide à développer et améliorer davantage DockerDiscordControl !",
                "Buy me a Coffee": "Offrez-moi un café",
                "Click here for Buy me a Coffee": "Cliquez ici pour Buy me a Coffee",
                "Click here for PayPal": "Cliquez ici pour PayPal",
                "Donations help with": "Les dons aident avec :",
                "Server and hosting costs": "Coûts de serveur et d'hébergement",
                "Development time for new features": "Temps de développement pour nouvelles fonctionnalités",
                "Bug fixes and support": "Corrections de bugs et support",
                "Documentation improvements": "Améliorations de la documentation",
                "This message is only shown every 2nd Sunday of the month": "Ce message n'est affiché que chaque 2ème dimanche du mois",
                # New donation broadcast translations  
                "If DDC helps you, please consider supporting ongoing development. Donations help cover hosting, CI, maintenance, and feature work.": "Avec votre don, vous ne soutenez pas seulement l'hébergement, CI, la maintenance et le développement – vous alimentez également la Donation Engine et faites évoluer notre Mech communautaire à travers ses niveaux d'évolution.\n\nChaque don = plus de carburant → le Mech évolue.",
                "Choose your preferred method:": "Choisissez votre méthode préférée :",
                "Click one of the buttons below to support DDC development": "Cliquez sur l'un des boutons ci-dessous pour soutenir le développement de DDC et alimenter le Mech.",
                "☕ Buy Me a Coffee": "☕ Buy Me a Coffee",
                "💳 PayPal": "💳 PayPal",
                "📢 Broadcast Donation": "📢 Enregistrer le don",
                "📢 Broadcast Your Donation": "Enregistrez votre don",
                "Your donation supports DDC and fuels the Donation Engine": "Votre don soutient DDC et alimente la Donation Engine – plus de carburant = plus d'évolution du Mech.",
                "Your Name": "Votre nom",
                "How should we display your name?": "Comment devons-nous afficher votre nom?",
                "Donation Amount (optional)": "Montant du don (optionnel)",
                "💰 Donation Amount (optional)": "💰 Montant du don (optionnel)",
                "Numbers only, $ will be added automatically": "Chiffres uniquement, $ sera ajouté automatiquement",
                "Share donation publicly?": "📢 Publier le don ?",
                "Remove X to keep private": "Supprimer X pour garder privé",
                "Cancel": "Annuler",
                "Submit": "Envoyer",
                "e.g. 5 Euro, $10, etc. (leave empty if you prefer not to share)": "par ex. 5 Euro, $10, etc. (laissez vide si vous préférez ne pas partager)",
                "10.50 (numbers only, $ will be added automatically)": "10.50 (Chiffres uniquement, $ sera ajouté automatiquement)",
                "💝 Donation received": "💝 Don reçu",
                "{donor_name} supports DDC with {amount} – thank you so much ❤️": "{donor_name} soutient DDC avec {amount} – merci beaucoup ❤️",
                "{donor_name} supports DDC – thank you so much ❤️": "{donor_name} soutient DDC – merci beaucoup ❤️",
                "✅ **Donation broadcast sent!**": "✅ **Annonce de don envoyée!**",
                "📢 Sent to **{count}** channels": "📢 Envoyé à **{count}** canaux",
                "⚠️ Failed to send to {count} channels": "⚠️ Échec de l'envoi à {count} canaux",
                "Thank you **{donor_name}** for your generosity! 🙏": "Merci **{donor_name}** pour votre générosité! 🙏",
                "✅ **Donation recorded privately!**": "✅ **Don enregistré privément!**",
                "Thank you **{donor_name}** for your generous support! 🙏": "Merci **{donor_name}** pour votre soutien généreux! 🙏",
                "Your donation has been recorded and helps fuel the Donation Engine.": "Votre don a été enregistré et aide à alimenter la Donation Engine.",
                "❌ Error sending donation broadcast. Please try again later.": "❌ Erreur lors de l'envoi de l'annonce de don. Veuillez réessayer plus tard.",
                "Thank you for your support!": "Merci pour votre soutien !",
                
                # Mech System translations (French)
                "Mech-onate": "Mech-onner",
                "Donation Engine": "Donation Engine",
                "Click + to view Mech details": "Cliquez sur + pour voir les détails du Mech",
                "Mech Status": "Statut du Mech",
                "Evolution": "Évolution",
                "Level": "Niveau",
                "Speed": "Vitesse", 
                "Fuel": "Carburant",
                "Fuel Consumption": "Consommation de carburant",
                "Glvl": "Glvl",
                "Fuel/Donate": "Donner pour alimenter",
                "Evolution level up - updating mech animation": "Montée de niveau d'évolution - mise à jour de l'animation du mech",
                "Donation received - updating status": "Don reçu - mise à jour du statut",
                "Donation recorded - updating fuel status": "Don enregistré - mise à jour du statut de carburant",
                "MECH EVOLUTION ACHIEVED!": "ÉVOLUTION DU MECH ATTEINTE!",
                "Your Mech has ascended to the next evolution stage: {evolution_name}": "Votre Mech a atteint le niveau d'évolution suivant: {evolution_name}",
                "The fuel system has been reset and refueled with the remaining surplus of ${surplus:.2f}.": "Le système de carburant a été réinitialisé et ravitaillé avec le surplus restant de ${surplus:.2f}.",
                "Significant Glvl change detected": "Changement significatif de Glvl détecté",
                "Upgrading to force_recreate=True due to significant Glvl change": "Mise à niveau vers force_recreate=True en raison d'un changement significatif de Glvl",
                
                # Evolution Names (French)
                "SCRAP MECH": "MECH FERRAILLE",
                "REPAIRED MECH": "MECH RÉPARÉ",
                "STANDARD MECH": "MECH STANDARD", 
                "ENHANCED MECH": "MECH AMÉLIORÉ",
                "ADVANCED MECH": "MECH AVANCÉ",
                "ELITE MECH": "MECH ÉLITE",
                "CYBER MECH": "MECH CYBER",
                "PLASMA MECH": "MECH PLASMA",
                "QUANTUM MECH": "MECH QUANTIQUE",
                "DIVINE MECH": "MECH DIVIN",
                "OMEGA MECH": "MECH OMEGA",
                "MAX EVOLUTION REACHED!": "ÉVOLUTION MAXIMALE ATTEINTE!",
            },
            # Fallback English (or add more languages)
            'en': {
                "Docker Control Panel": "Docker Control Panel",
                "Here you can control your Docker containers. Use the buttons below each server to perform actions.":
                    "Here you can control your Docker containers. Use the buttons below each server to perform actions.",
                "Available Commands": "Available Commands",
                "Shows this control panel": "Shows this control panel",
                "Shows server status (shortcut: /ss)": "Shows server status (shortcut: /ss)",
                "Directly control a container": "Directly control a container",
                "Shows help about available commands": "Shows help about available commands",
                "Shows the bot response time": "Shows the bot response time",
                "Edit container information": "Edit container information",
                "Container info is not configured for this container.": "Container info is not configured for this container.",
                "Container info is not enabled for **{display_name}**. Enable it in the web UI first.": "Container info is not enabled for **{display_name}**. Enable it in the web UI first.",
                "You don't have permission to view container info in this channel.": "You don't have permission to view container info in this channel.",
                "You do not have permission to edit container info in this channel.": "You do not have permission to edit container info in this channel.",
                "Container information is read-only in this channel.": "Container information is read-only in this channel.",
                "Container info updated for **{display_name}**": "Container info updated for **{display_name}**",
                "Text too long ({length}/250 characters). Please shorten it.": "Text too long ({length}/250 characters). Please shorten it.",
                "Error displaying container info. Please try again.": "Error displaying container info. Please try again.",
                "Error saving container info. Please try again.": "Error saving container info. Please try again.",
                
                # New /info command translations
                "This channel doesn't have permission to use the info command.": "This channel doesn't have permission to use the info command.",
                "This channel needs either status or control permissions to use the info command.": "This channel needs either status or control permissions to use the info command.",
                "Container '{}' not found in configuration.": "Container '{}' not found in configuration.",
                "No additional information is configured for container '{}'.": "No additional information is configured for container '{}'.",
                "An error occurred while retrieving container information. Please try again later.": "An error occurred while retrieving container information. Please try again later.",
                "Use `/info <servername>` to get detailed information about containers with ℹ️ indicators.": "Use `/info <servername>` to get detailed information about containers with ℹ️ indicators.",
                
                # Info Edit Modal translations
                "📝 Info Text": "📝 Info Text",
                "🌐 IP/URL": "🌐 IP/URL",
                "☑️ Enable Info Button": "☑️ Enable Info Button",
                "🌐 Show IP Address": "🌐 Show IP Address",
                "Example: Password: mypass123\nMax Players: 8\nMods: ModPack1, ModPack2": "Example: Password: mypass123\nMax Players: 8\nMods: ModPack1, ModPack2",
                "mydomain.com:7777 or 192.168.1.100:8080": "mydomain.com:7777 or 192.168.1.100:8080",
                "Type 'x' to enable, leave empty to disable": "Type 'x' to enable, leave empty to disable",
                "Type 'x' to show IP, leave empty to hide": "Type 'x' to show IP, leave empty to hide",
                "mydomain.com or 192.168.1.100": "mydomain.com or 192.168.1.100",
                "🔌 Port": "🔌 Port",
                "8080": "8080",
                "❌ Port must contain only numbers.": "❌ Port must contain only numbers.",
                "❌ Port must be between 1 and 65535.": "❌ Port must be between 1 and 65535.",
                
                # Spam Protection translations
                "Spam Protection Settings": "Spam Protection Settings",
                "Configure rate limiting to prevent spam and abuse of bot commands.": "Configure rate limiting to prevent spam and abuse of bot commands.",
                "Global Settings": "Global Settings", 
                "Enable Spam Protection": "Enable Spam Protection",
                "Show Cooldown Messages": "Show Cooldown Messages",
                "Log Rate Limit Violations": "Log Rate Limit Violations",
                "Max Commands/Minute": "Max Commands/Minute",
                "Max Button Clicks/Minute": "Max Button Clicks/Minute",
                "Per user limit": "Per user limit",
                "Command Cooldowns (seconds)": "Command Cooldowns (seconds)",
                "Button Cooldowns (seconds)": "Button Cooldowns (seconds)",
                "Start Button": "Start Button",
                "Stop Button": "Stop Button",
                "Restart Button": "Restart Button",
                "Info Button": "Info Button",
                "Refresh Button": "Refresh Button",
                "Spam protection settings saved successfully!": "Spam protection settings saved successfully!",
                "Failed to save container info. Please try again.": "Failed to save container info. Please try again.",
                # Donation messages
                "Show donation information to support the project": "Show donation information to support the project",
                "An error occurred while showing donation information. Please try again later.": "An error occurred while showing donation information. Please try again later.",
                "Support DockerDiscordControl": "Support DockerDiscordControl",
                "Hello! If you like DockerDiscordControl and want to support the development, I would be very happy about a small donation!": "Hello! If you like DockerDiscordControl and want to support the development, I would be very happy about a small donation! All the best, MAX",
                "Thank you for your interest!": "Thank you for your interest!",
                "Every support helps to further develop and improve DockerDiscordControl!": "Every support helps to further develop and improve DockerDiscordControl!",
                "Buy me a Coffee": "Buy me a Coffee",
                "Click here for Buy me a Coffee": "Click here for Buy me a Coffee",
                "Click here for PayPal": "Click here for PayPal",
                "Donations help with": "Donations help with:",
                "Server and hosting costs": "Server and hosting costs",
                "Development time for new features": "Development time for new features",
                "Bug fixes and support": "Bug fixes and support",
                "Documentation improvements": "Documentation improvements",
                "This message is only shown every 2nd Sunday of the month": "This message is only shown every 2nd Sunday of the month",
                # New donation broadcast translations
                "If DDC helps you, please consider supporting ongoing development. Donations help cover hosting, CI, maintenance, and feature work.": "With your donation, you're not just helping with hosting, CI, maintenance, and feature development – you're also fueling the Donation Engine and driving our community Mech through its evolution stages.\n\nEvery donation = more fuel → the Mech evolves.",
                "Choose your preferred method:": "Choose your preferred method:",
                "Click one of the buttons below to support DDC development": "Click one of the buttons below to support DDC development and power up the Mech.",
                "☕ Buy Me a Coffee": "☕ Buy Me a Coffee",
                "💳 PayPal": "💳 PayPal",
                "📢 Broadcast Donation": "📢 Record Donation",
                "📢 Broadcast Your Donation": "Record Your Donation",
                "Your donation supports DDC and fuels the Donation Engine": "Your donation supports DDC and fuels the Donation Engine – more fuel = more Mech evolution.",
                "Your Name": "Your Name",
                "How should we display your name?": "How should we display your name?",
                "Donation Amount (optional)": "Donation Amount (optional)",
                "💰 Donation Amount (optional)": "💰 Donation Amount (optional)",
                "Numbers only, $ will be added automatically": "Numbers only, $ will be added automatically",
                "Share donation publicly?": "📢 Share donation publicly?",
                "Remove X to keep private": "Remove X to keep private",
                "Cancel": "Cancel",
                "Submit": "Submit",
                "e.g. 5 Euro, $10, etc. (leave empty if you prefer not to share)": "e.g. 5 Euro, $10, etc. (leave empty if you prefer not to share)",
                "10.50 (numbers only, $ will be added automatically)": "10.50 (Numbers only, $ will be added automatically)",
                "💝 Donation received": "💝 Donation received",
                "{donor_name} supports DDC with {amount} – thank you so much ❤️": "{donor_name} supports DDC with {amount} – thank you so much ❤️",
                "{donor_name} supports DDC – thank you so much ❤️": "{donor_name} supports DDC – thank you so much ❤️",
                "✅ **Donation broadcast sent!**": "✅ **Donation broadcast sent!**",
                "📢 Sent to **{count}** channels": "📢 Sent to **{count}** channels",
                "⚠️ Failed to send to {count} channels": "⚠️ Failed to send to {count} channels",
                "Thank you **{donor_name}** for your generosity! 🙏": "Thank you **{donor_name}** for your generosity! 🙏",
                "✅ **Donation recorded privately!**": "✅ **Donation recorded privately!**",
                "Thank you **{donor_name}** for your generous support! 🙏": "Thank you **{donor_name}** for your generous support! 🙏",
                "Your donation has been recorded and helps fuel the Donation Engine.": "Your donation has been recorded and helps fuel the Donation Engine.",
                "❌ Error sending donation broadcast. Please try again later.": "❌ Error sending donation broadcast. Please try again later.",
                "Thank you for your support!": "Thank you for your support!",
                "DockerDiscordControl": "DockerDiscordControl",
                "This command is not allowed in this channel.": "This command is not allowed in this channel.",
                "Force update initiated. All status messages will be regenerated.": "Force update initiated. All status messages will be regenerated.",
                "Tip: Use": "Tip: Use",
                "to refresh all messages if needed.": "to refresh all messages if needed.",
                "Bot Language": "Bot Language",
                "Channel": "Channel",
                "No servers configured": "No servers configured",
                "No Docker containers are configured. Add servers in the web interface.": "No Docker containers are configured. Add servers in the web interface.",
                "Control panel for Docker containers": "Control panel for Docker containers",
                "Server Status": "Server Status",
                "Container": "Container",
                "Actions": "Actions",
                "Start": "Start",
                "Stop": "Stop",
                "Restart": "Restart",
                "Language": "Language",
                "Bot language set to": "Bot language set to",
                "Control Panel": "Control Panel",
                "No containers found": "No containers found",
                "Initiating forced update. New status messages will be sent.": "Initiating forced update. New status messages will be sent.",
                "No channels found where status updates are allowed.": "No channels found where status updates are allowed.",
                "No servers configured to update.": "No servers configured to update.",
                "The server is currently offline.": "The server is currently offline.",

                # Status texts
                "Status could not be retrieved.": "Status could not be retrieved.",
                "**Online**": "Online",
                "**Offline**": "Offline",
                "Loading": "Loading",
                "Status": "Status",
                "Performance": "Performance",
                "CPU": "CPU",
                "RAM": "RAM",
                "Uptime": "Uptime",
                "Detailed status not allowed.": "Detailed status not allowed.",
                "Last update": "Last update",
                "collapse": "-",
                "expand": "+",

                # Force Update texts
                "All status messages will be regenerated.": "All status messages will be regenerated.",
                "Error while updating messages: {error}": "Error while updating messages: {error}",

                # Command Success/Failure (English)
                "✅ Server Action Successful": "✅ Server Action Successful",
                "❌ Server Action Failed": "❌ Server Action Failed",
                "Server **{server_name}** is being processed {action_process_text}.": "Server **{server_name}** is being {action_process_text}.",
                "Server **{server_name}** could not be processed {action_process_text}.": "Server **{server_name}** could not be {action_process_text}.",
                "started_process": "started",
                "stopped_process": "stopped",
                "restarted_process": "restarted",
                "Docker command failed or timed out": "Docker command failed or timed out",
                "Action": "Action",
                "Executed by": "Executed by",
                "Error": "Error",
                "Docker container: {docker_name}": "Docker container: {docker_name}",
                "Pending..." : "Pending...",
                "Status is currently unknown.": "Status is currently unknown.",

                # Schedule Command Texts
                "This command can only be used in server channels.": "This command can only be used in server channels.",
                "You do not have permission to use schedule commands in this channel.": "You do not have permission to use schedule commands in this channel.",
                "Invalid time format. Please use HH:MM or e.g., 2:30pm.": "Invalid time format. Please use HH:MM or e.g., 2:30pm.",
                "Invalid year format. Please use YYYY format (e.g., 2025).": "Invalid year format. Please use YYYY format (e.g., 2025).",
                "Invalid month format. Please use month name (e.g., January) or number (1-12).": "Invalid month format. Please use month name (e.g., January) or number (1-12).",
                "Day must be between 1 and 31.": "Day must be between 1 and 31.",
                "Invalid day format. Please use a number (1-31).": "Invalid day format. Please use a number (1-31).",
                "Cannot schedule task: The calculated execution time is invalid (e.g., in the past).": "Cannot schedule task: The calculated execution time is invalid (e.g., in the past).",
                "Cannot schedule task: It conflicts with an existing task for the same container within a 10-minute window.": "Cannot schedule task: It conflicts with an existing task for the same container within a 10-minute window.",
                "Task for {container_name} scheduled for {next_run_formatted}.": "Task for {container_name} scheduled for {next_run_formatted}.",
                "Failed to schedule task. It might conflict with an existing task (time collision) or another error occurred.": "Failed to schedule task. It might conflict with an existing task (time collision) or another error occurred.",
                "An error occurred: {error}": "An error occurred: {error}",
                "Failed to schedule task. Possible time collision or other error.": "Failed to schedule task. Possible time collision or other error.",
                "Invalid weekday format. Please use a weekday name like 'Monday' or 'Montag'.": "Invalid weekday format. Please use a weekday name like 'Monday' or 'Montag'.",
                "Task for {container_name} scheduled weekly on {weekday_name} at {hour:02d}:{minute:02d}.": "Task for {container_name} scheduled weekly on {weekday_name} at {hour:02d}:{minute:02d}.",
                "Cannot schedule task: Invalid parameters or past execution time.": "Cannot schedule task: Invalid parameters or past execution time.",
                "Cannot schedule task: Conflicts with an existing task within 10 minutes.": "Cannot schedule task: Conflicts with an existing task within 10 minutes.",
                "Task for {container_name} scheduled monthly on day {day} at {hour:02d}:{minute:02d}.": "Task for {container_name} scheduled monthly on day {day} at {hour:02d}:{minute:02d}.",
                "DockerDiscordControl - Scheduling Commands": "DockerDiscordControl - Scheduling Commands",
                "Specialized commands are available for different scheduling cycles:": "Specialized commands are available for different scheduling cycles:",
                "Schedule a **one-time** task with year, month, day, and time.": "Schedule a **one-time** task with year, month, day, and time.",
                "Schedule a **daily** task at the specified time.": "Schedule a **daily** task at the specified time.",
                "Schedule a **weekly** task on the specified weekday and time.": "Schedule a **weekly** task on the specified weekday and time.",
                "Schedule a **monthly** task on the specified day and time.": "Schedule a **monthly** task on the specified day and time.",
                "Schedule a **yearly** task on the specified month, day, and time.": "Schedule a **yearly** task on the specified month, day, and time.",
                "Task for {container_name} scheduled yearly on {month_name} {day} at {hour:02d}:{minute:02d}.": "Task for {container_name} scheduled yearly on {month_name} {day} at {hour:02d}:{minute:02d}.",
                "Next execution: {time}": "Next execution: {time}",
                "No next execution time scheduled": "No next execution time scheduled",
                "Cycle": "Cycle",

                # Weekday translations
                "Monday": "Monday",
                "Tuesday": "Tuesday",
                "Wednesday": "Wednesday",
                "Thursday": "Thursday",
                "Friday": "Friday",
                "Saturday": "Saturday",
                "Sunday": "Sunday",
                "monday": "monday",
                "tuesday": "tuesday",
                "wednesday": "wednesday",
                "thursday": "thursday",
                "friday": "friday",
                "saturday": "saturday",
                "sunday": "sunday",

                # Month translations
                "January": "January",
                "February": "February",
                "March": "March",
                "April": "April",
                "May": "May",
                "June": "June",
                "July": "July",
                "August": "August",
                "September": "September",
                "October": "October",
                "November": "November",
                "December": "December",

                "Only showing the next {count} tasks. Use the Web UI to view all.": "Only showing the next {count} tasks. Use the Web UI to view all.",
                "You don't have permission to schedule tasks for '{container}'.": "You don't have permission to schedule tasks for '{container}'.",
                "Note on Day Selection": "Note on Day Selection",
                "Due to Discord's 25-option limit for autocomplete, only a strategic selection of days (1-5, 7, 9, 10, 12-15, 17, 18, 20-22, 24-28, 30, 31) is shown initially. You can still type any day number manually.": "Due to Discord's 25-option limit for autocomplete, only a strategic selection of days (1-5, 7, 9, 10, 12-15, 17, 18, 20-22, 24-28, 30, 31) is shown initially. You can still type any day number manually.",
                "Shows information about all scheduled tasks.": "Shows information about all scheduled tasks.",
                
                # Container Info Modal translations (English - defaults)
                "📝 Info Text": "📝 Info Text",
                "☑️ Enable Info Button": "☑️ Enable Info Button",
                "Type 'x' to enable, leave empty to disable": "Type 'x' to enable, leave empty to disable",
                "🌐 Show IP Address": "🌐 Show IP Address",
                "Type 'x' to show IP, leave empty to hide": "Type 'x' to show IP, leave empty to hide",
                "📝 Custom Info Text (250 chars max)": "📝 Custom Info Text (250 chars max)",
                "Example: Password: mypass123\\nMax Players: 8\\nMods: ModPack1, ModPack2": "Example: Password: mypass123\\nMax Players: 8\\nMods: ModPack1, ModPack2",
                "🌐 IP/URL": "🌐 IP/URL",
                "🌐 Custom IP/URL (optional)": "🌐 Custom IP/URL (optional)",
                "mydomain.com:7777 or 192.168.1.100:8080": "mydomain.com:7777 or 192.168.1.100:8080",
                "Currently: {status}, IP {ip_status}": "Currently: {status}, IP {ip_status}",
                "enabled": "enabled",
                "disabled": "disabled", 
                "shown": "shown",
                "hidden": "hidden",
                "⚙️ Settings": "⚙️ Settings",
                "Settings": "Settings",
                "Type: enabled, show_ip (or leave empty to turn off both)": "Type: enabled, show_ip (or leave empty to turn off both)",
                "❌ Custom text too long ({length}/250 characters). Please shorten it.": "❌ Custom text too long ({length}/250 characters). Please shorten it.",
                "\\n⚠️ IP format might be invalid: `{ip}`": "\\n⚠️ IP format might be invalid: `{ip}`",
                "✅ Container Info Updated": "✅ Container Info Updated",
                "Successfully updated information for **{name}**": "Successfully updated information for **{name}**",
                "📝 Custom Text ({count}/250 chars)": "📝 Custom Text ({count}/250 chars)",
                "🌐 Custom IP/URL": "🌐 Custom IP/URL",
                "✅ Info button enabled": "✅ Info button enabled",
                "❌ Info button disabled": "❌ Info button disabled",
                "🌐 Show IP address": "🌐 Show IP address",
                "🔒 Hide IP address": "🔒 Hide IP address",
                "⚙️ Settings": "⚙️ Settings",
                "❌ Failed to save container info for **{name}**. Please try again.": "❌ Failed to save container info for **{name}**. Please try again.",
                "❌ Failed to save container info for **{name}**. Check permissions on config directory.": "❌ Failed to save container info for **{name}**. Check permissions on config directory.",
                "❌ An error occurred while saving container info: {error}": "❌ An error occurred while saving container info: {error}",
                "❌ An error occurred while saving container info. Please try again.": "❌ An error occurred while saving container info. Please try again.",
                
                # Period texts for schedule_info
                "all": "all",
                "next_week": "next_week",
                "next_month": "next_month",
                "today": "today",
                "tomorrow": "tomorrow",
                "next_day": "next_day",
                "Scheduled tasks for the next 24 hours": "Scheduled tasks for the next 24 hours",
                "Scheduled tasks for the next week": "Scheduled tasks for the next week",
                "Scheduled tasks for the next month": "Scheduled tasks for the next month",
                "All active scheduled tasks": "All active scheduled tasks",
                "No active scheduled tasks found for the specified criteria.": "No active scheduled tasks found for the specified criteria.",
                "No active scheduled tasks found for the specified period.": "No active scheduled tasks found for the specified period.",
                "All tasks have been marked as expired or inactive.": "All tasks have been marked as expired or inactive.",
                "An error occurred while fetching scheduled tasks. Please check the logs.": "An error occurred while fetching scheduled tasks. Please check the logs.",
                
                # Task descriptions
                "Weekly {action} on {weekday_name} at {hour:02d}:{minute:02d}": "Weekly {action} on {weekday_name} at {hour:02d}:{minute:02d}",

                # Ping Command
                "Pong! Latency: {latency:.2f} ms": "Pong! Latency: {latency:.2f} ms",
                
                # Help Command
                "DockerDiscordControl - Help": "DockerDiscordControl - Help",
                "Here are the available commands:": "Here are the available commands:",
                "Displays the status of all configured Docker containers.": "Displays the status of all configured Docker containers.",

                # Heartbeat
                "❤️ Heartbeat signal at {timestamp}": "❤️ Heartbeat signal at {timestamp}",

                # Error messages
                "Error during execution: {error}": "Error during execution: {error}",
                
                # Mech System translations (English)
                "Mech-onate": "Mech-onate",
                "Donation Engine": "Donation Engine",
                "Click + to view Mech details": "Click + to view Mech details",
                "Mech Status": "Mech Status",
                "Evolution": "Evolution",
                "Level": "Level",
                "Speed": "Speed", 
                "Fuel": "Fuel",
                "Fuel Consumption": "Fuel Consumption",
                "Glvl": "Glvl",
                "Fuel/Donate": "Donate to Fuel",
                "Evolution level up - updating mech animation": "Evolution level up - updating mech animation",
                "Donation received - updating status": "Donation received - updating status",
                "Donation recorded - updating fuel status": "Donation recorded - updating fuel status",
                "MECH EVOLUTION ACHIEVED!": "MECH EVOLUTION ACHIEVED!",
                "Your Mech has ascended to the next evolution stage: {evolution_name}": "Your Mech has ascended to the next evolution stage: {evolution_name}",
                "The fuel system has been reset and refueled with the remaining surplus of ${surplus:.2f}.": "The fuel system has been reset and refueled with the remaining surplus of ${surplus:.2f}.",
                "Significant Glvl change detected": "Significant Glvl change detected",
                "Upgrading to force_recreate=True due to significant Glvl change": "Upgrading to force_recreate=True due to significant Glvl change",
                
                # Evolution Names (English) 
                "SCRAP MECH": "SCRAP MECH",
                "REPAIRED MECH": "REPAIRED MECH",
                "STANDARD MECH": "STANDARD MECH",
                "ENHANCED MECH": "ENHANCED MECH", 
                "ADVANCED MECH": "ADVANCED MECH",
                "ELITE MECH": "ELITE MECH",
                "CYBER MECH": "CYBER MECH",
                "PLASMA MECH": "PLASMA MECH",
                "QUANTUM MECH": "QUANTUM MECH",
                "DIVINE MECH": "DIVINE MECH", 
                "OMEGA MECH": "OMEGA MECH",
                "MAX EVOLUTION REACHED!": "MAXIMALE EVOLUTION ERREICHT!",
            }
            # Add other languages here if needed
        }

    def get_current_language(self):
        """Returns the current language from the configuration"""
        # Try to get language from cached config first for better performance
        try:
            from utils.config_cache import get_cached_config
            config = get_cached_config()
        except ImportError:
            # Fallback to direct config loading if cache is not available
            config = load_config()
        
        # Ensure the default is 'en'
        lang_from_config = config.get('language', 'en') 
        self._current_language = lang_from_config
        # Ensure the language exists in our translations, default to 'en' otherwise
        if self._current_language not in self._translations:
             self._current_language = 'en'
        return self._current_language

    @lru_cache(maxsize=128)
    def _(self, text):
        """Translates the text into the current language with caching"""
        # Clear cache if language has changed to ensure fresh translations
        current_lang = self.get_current_language()
        if hasattr(self, '_cached_language') and self._cached_language != current_lang:
            # Language changed, clear the translation cache
            self._.cache_clear()
        self._cached_language = current_lang
        
        language = current_lang

        # Try the specific language
        if language in self._translations:
            translation = self._translations[language].get(text)
            if translation:
                 return translation

        # Fallback to English if not found in the specific language
        if language != 'en' and 'en' in self._translations:
            translation = self._translations['en'].get(text)
            if translation:
                return translation # Return English fallback

        return text # Return original text if no translation is found anywhere

# Global instance for easy access
translation_manager = TranslationManager()

# Custom simple translation function
def _(text):
    """Optimized translation function with caching"""
    return translation_manager._(text)

# Make translations globally available for direct access
@lru_cache(maxsize=1)
def get_translations():
    """Returns the translation dictionary with all languages (cached)"""
    return translation_manager._translations 