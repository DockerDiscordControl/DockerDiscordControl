#!/bin/bash
# ============================================================================ #
# Fix display_name format in container JSON files
# Converts display_name from list format to single string
# Handles multi-line JSON arrays
# ============================================================================ #

echo "🔧 Fixing display_name format in container JSON files..."
echo "=================================================="

# Change to the dockerdiscordcontrol directory
cd /mnt/user/appdata/dockerdiscordcontrol

# Create backup directory with timestamp
BACKUP_DIR="config.backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
echo "📁 Created backup directory: $BACKUP_DIR"

# Counter for statistics
FIXED=0
SKIPPED=0

# Process each JSON file in config/containers/
for json_file in config/containers/*.json; do
    if [ -f "$json_file" ]; then
        filename=$(basename "$json_file")

        # Create backup
        cp "$json_file" "$BACKUP_DIR/$filename"

        # Check if file contains display_name array
        if grep -q '"display_name": \[' "$json_file"; then
            echo "📝 Processing $filename..."

            # Use awk to handle multi-line array and extract first element
            awk '
            /"display_name": \[/ {
                # Found the start of display_name array
                in_array = 1
                next
            }
            in_array && /^[[:space:]]*".*"/ {
                # Extract the first array element (remove quotes and comma)
                gsub(/^[[:space:]]*"/, "")
                gsub(/"[,]?[[:space:]]*$/, "")
                first_name = $0
                in_array = 0
                found_name = 1
            }
            in_array && /\]/ {
                # End of array without finding a name
                in_array = 0
            }
            END {
                if (found_name) {
                    print first_name
                }
            }
            ' "$json_file" > /tmp/display_name.tmp

            first_name=$(cat /tmp/display_name.tmp)
            rm -f /tmp/display_name.tmp

            if [ -n "$first_name" ]; then
                echo "  → Converting to: '$first_name'"

                # Create a temporary file with the fixed content
                awk -v name="$first_name" '
                BEGIN { in_array = 0; skip_lines = 0 }
                /"display_name": \[/ {
                    # Replace the array start with single string
                    print "  \"display_name\": \"" name "\","
                    in_array = 1
                    skip_lines = 1
                    next
                }
                in_array {
                    # Skip array content lines
                    if (/\]/) {
                        in_array = 0
                        skip_lines = 0
                    }
                    next
                }
                !skip_lines {
                    print
                }
                ' "$json_file" > "$json_file.tmp"

                mv "$json_file.tmp" "$json_file"
                ((FIXED++))
            else
                echo "  ⚠️  Could not extract name from list"
                ((SKIPPED++))
            fi
        else
            # Check if display_name exists as a string
            if grep -q '"display_name": "' "$json_file"; then
                current_name=$(grep '"display_name"' "$json_file" | sed -n 's/.*"display_name": "\([^"]*\)".*/\1/p')
                echo "✅ $filename: Already a string ('$current_name')"
            else
                echo "ℹ️  $filename: No display_name field"
            fi
            ((SKIPPED++))
        fi
    fi
done

echo ""
echo "📊 Summary:"
echo "  - Fixed: $FIXED files"
echo "  - Skipped: $SKIPPED files"

if [ $FIXED -gt 0 ]; then
    echo "  - Backup saved to: $BACKUP_DIR"
    echo ""
    echo "✨ Display names have been fixed!"
    echo ""
    echo "🔄 Restarting Docker container to apply changes..."
    docker restart dockerdiscordcontrol
    echo "✅ Container restarted. Changes should now be visible in the Web UI."
else
    echo ""
    echo "✅ No changes needed - all display names are already in correct format!"
fi