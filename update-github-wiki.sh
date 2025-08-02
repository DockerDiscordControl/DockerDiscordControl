#!/bin/bash

# Script to update GitHub Wiki from main repo wiki folder

echo "📚 Updating GitHub Wiki from main repository..."

# Clone the wiki repo
echo "1. Cloning wiki repository..."
git clone https://github.com/DockerDiscordControl/DockerDiscordControl.wiki.git wiki-temp

# Copy updated files from main repo
echo "2. Copying updated wiki files..."
cp -r wiki/* wiki-temp/

# Navigate to wiki repo
cd wiki-temp

# Check for changes
if git diff --quiet; then
    echo "❌ No changes detected. Wiki is already up to date."
    cd ..
    rm -rf wiki-temp
    exit 0
fi

# Stage and commit changes
echo "3. Committing changes..."
git add -A
git commit -m "📚 Update wiki from main repository

- Removed excessive emoji usage
- Fixed all V3.0 references (now v1.1.3c)
- Removed AI-like marketing language
- Made documentation more professional
- Fixed version numbers throughout
- Cleaned up overly enthusiastic phrasing"

# Push to GitHub
echo "4. Pushing to GitHub Wiki..."
git push

echo "✅ Wiki updated successfully!"

# Cleanup
cd ..
rm -rf wiki-temp

echo ""
echo "The GitHub Wiki has been updated with all the fixes from the main repository."
echo "Check it at: https://github.com/DockerDiscordControl/DockerDiscordControl/wiki"