#!/bin/bash
# Install hongyan's git hooks into an existing clone.
#
# Hooks are not versioned by git, so a clone starts with none — which is
# exactly the state in which the owner's ACI once reached a public commit.
# install.sh calls this; run it by hand after cloning.
set -eu
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
hooks="$(git -C "$repo" rev-parse --git-path hooks)"

mkdir -p "$hooks"
for hook in pre-commit pre-push; do
    src="$repo/scripts/$hook"
    dst="$hooks/$hook"
    if [ -e "$dst" ] && ! [ -L "$dst" ]; then
        echo "install-hooks: $dst exists and is not a symlink — left alone" >&2
        continue
    fi
    ln -sfn "$src" "$dst"
    chmod +x "$src"
    echo "installed $hook"
done
