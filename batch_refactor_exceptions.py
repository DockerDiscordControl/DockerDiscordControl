#!/usr/bin/env python3
"""
Batch refactor all generic 'except Exception' handlers to specific exceptions.
Phase 4 Final - Automated Refactoring Script
"""
import os
import re
import subprocess
from pathlib import Path

# Exception patterns based on context
PATTERNS = {
    # File operations
    r'(open|read|write|load|save|dump|json\.|Path|file)':
        '(IOError, OSError, PermissionError, json.JSONDecodeError)',

    # Discord operations
    r'(discord\.|message\.|channel\.|guild\.|send|edit|fetch|interaction\.)':
        '(discord.HTTPException, discord.Forbidden, discord.NotFound)',

    # Docker operations
    r'(docker|container|get_docker|DockerClient)':
        '(docker.errors.DockerException, docker.errors.NotFound, docker.errors.APIError)',

    # Async operations
    r'(asyncio\.|await |async )':
        '(asyncio.TimeoutError, asyncio.CancelledError, RuntimeError)',

    # Config/data operations
    r'(config|get\(|\.get\(|\[)':
        '(KeyError, AttributeError, TypeError, ValueError)',

    # Import operations
    r'(import |from .* import)':
        '(ImportError, AttributeError, ModuleNotFoundError)',

    # Service calls
    r'(service|Service|get_.*_service)':
        '(RuntimeError, AttributeError, TypeError)',
}

def get_exception_types_for_context(lines_before, lines_after):
    """Determine appropriate exception types based on surrounding context."""
    context = '\n'.join(lines_before + lines_after).lower()

    exceptions = set()

    # Check each pattern
    if re.search(r'open\(|read|write|\.json|json\.|dump|load', context):
        exceptions.update(['IOError', 'OSError', 'PermissionError'])
        if 'json' in context:
            exceptions.add('json.JSONDecodeError')

    if re.search(r'discord\.|message|channel|guild|send|edit|fetch|interaction', context):
        exceptions.update(['discord.HTTPException', 'discord.Forbidden', 'discord.NotFound'])

    if re.search(r'docker|container', context):
        exceptions.update(['docker.errors.DockerException', 'docker.errors.APIError'])

    if re.search(r'asyncio\.|await |async def', context):
        exceptions.update(['asyncio.TimeoutError', 'asyncio.CancelledError'])

    if re.search(r'\.get\(|\[\'|ImportError|import ', context):
        exceptions.update(['KeyError', 'AttributeError', 'TypeError'])

    if re.search(r'import |from .* import', context):
        exceptions.update(['ImportError', 'ModuleNotFoundError'])

    # Always include RuntimeError as fallback for service/business logic
    exceptions.add('RuntimeError')

    # Sort for consistency
    return sorted(exceptions)

def refactor_file(filepath):
    """Refactor a single file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except (IOError, OSError, PermissionError, RuntimeError) as e:
        print(f"❌ Could not read {filepath}: {e}")
        return 0

    changes = 0
    new_lines = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Check if this is an 'except Exception' line
        if re.match(r'\s*except Exception', line):
            # Get context (5 lines before and after)
            start = max(0, i - 5)
            end = min(len(lines), i + 6)
            lines_before = [lines[j] for j in range(start, i)]
            lines_after = [lines[j] for j in range(i + 1, end)]

            # Determine appropriate exceptions
            exceptions = get_exception_types_for_context(lines_before, lines_after)

            if exceptions:
                # Replace the line
                indent = re.match(r'(\s*)except', line).group(1)
                has_as = ' as e' in line or ' as ex' in line or ' as err' in line
                var_part = ' as e' if has_as else ''

                new_line = f"{indent}except ({', '.join(exceptions)}){var_part}:\n"
                new_lines.append(new_line)

                # Check if next line is a logger.error without exc_info
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    if 'logger.error' in next_line and 'exc_info' not in next_line and has_as:
                        # Add exc_info=True
                        next_line = next_line.rstrip()
                        if next_line.endswith(')'):
                            next_line = next_line[:-1] + ', exc_info=True)\n'
                        else:
                            next_line = next_line + ', exc_info=True\n'
                        new_lines.append(next_line)
                        i += 2  # Skip the next line since we modified it
                        changes += 1
                        continue

                changes += 1
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

        i += 1

    if changes > 0:
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            return changes
        except (IOError, OSError, PermissionError, RuntimeError) as e:
            print(f"❌ Could not write {filepath}: {e}")
            return 0

    return 0

def find_files_with_exceptions():
    """Find all Python files with generic Exception handlers."""
    result = subprocess.run(
        ['find', '/Volumes/appdata/dockerdiscordcontrol', '-name', '*.py',
         '-type', 'f', '-not', '-path', '*/.git/*', '-not', '-path', '*/__pycache__/*',
         '-not', '-path', '*/tests/*'],
        capture_output=True,
        text=True
    )

    files_with_handlers = []
    for filepath in result.stdout.strip().split('\n'):
        if not filepath:
            continue
        try:
            count = subprocess.run(
                ['grep', '-c', 'except Exception', filepath],
                capture_output=True,
                text=True
            )
            if count.returncode == 0:
                handler_count = int(count.stdout.strip())
                if handler_count > 0:
                    files_with_handlers.append((filepath, handler_count))
        except:
            pass

    return sorted(files_with_handlers, key=lambda x: x[1], reverse=True)

def main():
    print("🔍 Finding files with generic Exception handlers...")
    files = find_files_with_exceptions()

    print(f"\n📊 Found {len(files)} files with generic handlers")
    total_changes = 0

    for filepath, count in files:
        print(f"\n🔧 Processing {Path(filepath).name} ({count} handlers)...")
        changes = refactor_file(filepath)
        if changes > 0:
            total_changes += changes
            print(f"   ✅ Refactored {changes} handlers")
        else:
            print(f"   ⚠️  No changes made")

    print(f"\n🎉 Total: {total_changes} handlers refactored across {len(files)} files")

    # Verify
    print("\n🔍 Verifying...")
    remaining = find_files_with_exceptions()
    print(f"📊 Remaining files with generic handlers: {len(remaining)}")

    if remaining:
        print("\n⚠️  Still remaining:")
        for filepath, count in remaining[:10]:
            print(f"   - {Path(filepath).name}: {count} handlers")

if __name__ == '__main__':
    main()
