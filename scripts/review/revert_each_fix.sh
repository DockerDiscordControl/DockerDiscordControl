#!/bin/bash
# A test that cannot fail is not a test.
#
# For each fix commit: reverse-apply ONLY its production-code hunks (test files
# and docs are left exactly as they are), run the guard group, record whether
# anything went red, restore. A fix that can be reverted while the suite stays
# green has no guard, whatever its test file claims.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"

#   scripts/review/revert_each_fix.sh commits.txt [test group] [output file]
#
# where commits.txt holds one "<sha> <subject>" per line, e.g.
#   git log --format="%h %s" --grep="review [A-Z][0-9]" -40 \
#       | grep -E "🔒|✨" > commits.txt
#
# Needs DDC_TEST_HOST, like scripts/ddc_test.sh. One container per commit, so
# budget roughly 75 seconds each.

COMMITS="${1:?usage: revert_each_fix.sh <commits file> [group] [out]}"
GROUP="${2:-tests/spec}"
OUT="${3:-./revert_each_fix_result.txt}"
: > "$OUT"

while read -r sha subject; do
    [ -z "$sha" ] && continue

    # Production files only: not tests, not docs.
    files=$(git show --name-only --format= "$sha" \
            | grep -vE '^(tests/|docs/)' | grep -E '\.py$' || true)
    if [ -z "$files" ]; then
        printf '%-9s SKIP   no production file changed   %s\n' "$sha" "$subject" >> "$OUT"
        continue
    fi

    # Reverse-apply just those paths.
    if ! git show "$sha" -- $files | git apply --reverse --quiet 2>/dev/null; then
        printf '%-9s SKIP   cannot reverse-apply cleanly  %s\n' "$sha" "$subject" >> "$OUT"
        git checkout -- $files 2>/dev/null
        continue
    fi

    result=$(scripts/ddc_test.sh "$GROUP" 2>&1 \
             | grep -E '^=+ .*(passed|failed|error)' | tail -1)
    git checkout -- $files 2>/dev/null

    if echo "$result" | grep -q "failed"; then
        n=$(echo "$result" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+')
        printf '%-9s CAUGHT %s red   %s\n' "$sha" "$n" "$subject" >> "$OUT"
    elif echo "$result" | grep -q "passed"; then
        printf '%-9s SURVIVED (all green!)  %s\n' "$sha" "$subject" >> "$OUT"
    else
        printf '%-9s ERROR  %s  %s\n' "$sha" "$result" "$subject" >> "$OUT"
    fi
done < "$COMMITS"

echo "--- done ---" >> "$OUT"
cat "$OUT"
