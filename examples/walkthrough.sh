#!/usr/bin/env bash
# The governance loop end to end on the committed sample, in a scratch folder:
#   register the trial -> freeze the rule -> score (only if the freeze holds) -> record the result -> try to cheat.
set -euo pipefail
cd "$(dirname "$0")/.."
W=$(mktemp -d)
cp examples/PREREG_TEMPLATE.md "$W/PREREG.md"
cp examples/spec_sample.json "$W/spec.json"
sed -i.bak "s#data/sample.csv.gz#$PWD/examples/data/sample.csv.gz#" "$W/spec.json" && rm "$W/spec.json.bak"
SA="python -m signal_audit"

echo "== 1. register the trial before anything is scored (K = looks at the data that produced the idea)"
$SA ledger register --ledger "$W/trials.jsonl" --id SAMPLE-001/v1 --k-looks 18 \
    --body '{"rule": "buy next open after A/A+ short, sell 20 bars later", "prereg": "PREREG.md"}'

echo "== 2. freeze the written rule, the spec and the scorer's own source"
$SA freeze --out "$W/prereg.lock.json" "$W/PREREG.md" "$W/spec.json"

echo "== 3. score: the freeze is checked first, the placebo gate runs inside, the verdict rule is code"
$SA score --spec "$W/spec.json" --lock "$W/prereg.lock.json" --out "$W/result.json"

echo "== 4. record the result (a result is not a new trial)"
V=$(python -c "import json,sys; print(json.load(open(sys.argv[1]))['verdict'])" "$W/result.json")
$SA ledger result --ledger "$W/trials.jsonl" --id SAMPLE-001/v1 --body "{\"verdict\": \"$V\"}"
$SA ledger show --ledger "$W/trials.jsonl"

echo "== 5. try to move the goalposts after seeing the result: change the hold from 20 to 10 bars"
sed -i.bak 's/"hold": 20/"hold": 10/' "$W/spec.json" && rm "$W/spec.json.bak"
$SA score --spec "$W/spec.json" --lock "$W/prereg.lock.json" || echo "   (refused, as it should be: a change is a NEW registered variant)"

echo "== 6. try to quietly re-register the same id"
$SA ledger register --ledger "$W/trials.jsonl" --id SAMPLE-001/v1 --k-looks 18 || echo "   (refused)"

echo "== 7. edit history: rewrite the recorded verdict in the ledger file"
python - "$W/trials.jsonl" <<'PY'
import sys; p = sys.argv[1]; s = open(p).read().replace('NOT SUPPORTED', 'SUPPORTED'); open(p, 'w').write(s)
PY
$SA ledger verify --ledger "$W/trials.jsonl" || echo "   (tampering detected)"
echo "scratch folder: $W"
