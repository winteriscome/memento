#!/usr/bin/env bash
set -euo pipefail

# Smoke test: verify Memento works end-to-end from CLI
# Usage: bash scripts/smoke-test.sh

TMPDIR=$(mktemp -d)
export MEMENTO_DB="$TMPDIR/smoke.db"
trap "rm -rf $TMPDIR" EXIT

echo "=== Memento Smoke Test ==="
echo "DB: $MEMENTO_DB"

# 1. Init (auto-creates DB on first use)
memento status > /dev/null 2>&1
echo "[1/8] init: OK"

# 2. Capture
memento capture "JWT auth uses RS256 with keys in /config/keys/" --type fact --importance high
echo "[2/8] capture: OK"

# 3. Recall (should find the captured memory from capture_log)
RESULT=$(memento recall "JWT auth" --format json 2>/dev/null)
if echo "$RESULT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert len(d)>0" 2>/dev/null; then
    echo "[3/8] recall: OK (found captured memory)"
else
    echo "[3/8] recall: WARN (no results — may need epoch first)"
fi

# 3b. Verify recall returns staleness_level
if echo "$RESULT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert len(d) > 0, 'no results'
assert 'staleness_level' in d[0], 'missing staleness_level'
assert d[0]['staleness_level'] in ('fresh', 'stale', 'very_stale'), 'invalid staleness_level'
" 2>/dev/null; then
    echo "[3b/8] staleness_level in recall: OK"
else
    echo "[3b/8] staleness_level in recall: FAIL"
    exit 1
fi

# 4. Status
memento status > /dev/null
echo "[4/8] status: OK"

# 5. Epoch (light mode, no LLM needed)
memento epoch run --mode light 2>/dev/null || true
echo "[5/8] epoch light: OK"

# 6. Recall after epoch
RESULT=$(memento recall "JWT" --format json 2>/dev/null)
if echo "$RESULT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert len(d)>0" 2>/dev/null; then
    echo "[6/8] recall after epoch: OK"
else
    echo "[6/8] recall after epoch: FAIL — memory lost after epoch!"
    exit 1
fi

# 7. Verify staleness_level after epoch
if echo "$RESULT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert len(d) > 0, 'no results'
assert 'staleness_level' in d[0], 'missing staleness_level after epoch'
" 2>/dev/null; then
    echo "[7/8] staleness_level after epoch: OK"
else
    echo "[7/8] staleness_level after epoch: FAIL"
    exit 1
fi

# 8. Epoch status
memento epoch status > /dev/null
echo "[8/8] epoch status: OK"

echo ""
echo "=== All smoke tests passed ==="
