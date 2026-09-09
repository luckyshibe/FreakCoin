#!/bin/sh

if [ $# -gt 0 ]; then
    FILE="$1"
    shift
    if [ -f "$FILE" ]; then
        INFO="$(head -n 1 "$FILE")"
    fi
else
    echo "Usage: $0 <filename>"
    exit 1
fi

if command -v git >/dev/null 2>&1; then
    # A commit is available even in a clone without release tags.
    COMMIT="$(git rev-parse --verify HEAD 2>/dev/null)"
    if [ -n "$COMMIT" ] && ! git diff-index --quiet HEAD --; then
        COMMIT="$COMMIT-dirty"
    fi

    # get a string like "2012-04-10 16:27:19 +0200"
    TIME="$(git log -n 1 --format="%ci")"
fi

if [ -n "$COMMIT" ]; then
    NEWINFO="#define BUILD_COMMIT \"$COMMIT\""
else
    NEWINFO="// No build information available"
fi

# only update build.h if necessary
if [ "$INFO" != "$NEWINFO" ]; then
    echo "$NEWINFO" >"$FILE"
    echo "#define BUILD_DATE \"$TIME\"" >>"$FILE"
fi
