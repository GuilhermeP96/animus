#!/usr/bin/env bash
set -euo pipefail
umask 077
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_dir="$repo/skills/animus-rag"
destination="${ANIMUS_SKILL_DEST:-/root/.agents/skills/animus-rag}"
archive="${ANIMUS_SKILL_BACKUP:-/var/lib/vps-hub/rollback/animus-rag}"
mkdir -p "$archive" "$destination"
chmod 700 "$archive"
if [[ -f "$destination/SKILL.md" ]]; then
    tar czf "$archive/pre-install-$(date -u +%Y%m%dT%H%M%S).tar.gz" -C "$destination" .
fi
cp -a "$source_dir/." "$destination/"
while IFS= read -r -d '' file; do
    relative="${file#"$source_dir/"}"
    cmp "$file" "$destination/$relative"
done < <(find "$source_dir" -type f ! -name '*.pyc' -print0)
echo 'Animus RAG skill installed; all source files match.'
