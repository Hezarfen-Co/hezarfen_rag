#!/usr/bin/env bash
# The LOCAL full gate: the "special path" where this machine proves the
# suite instead of a GitHub runner.
#
# Why it exists: the same suite is ~30s here and HANGS on a 2-core runner
# (measured: run 35297989416 sat at 7% for 73 minutes until it was cancelled
# by hand, and every push since 2026-09-17 17:54 burned 1h-3h20m the same
# way). When you have run this script, commit the `Local-Gate:` trailer it
# prints (`--amend` writes it for you) and the push carries proof: the
# workflow's "Decide test gate" step verifies the trailer against HEAD^{tree}
# and then skips the runner suite, so CI only builds, packs and uploads.
#
# Default path (nothing here): push without a trailer and GitHub runs
# everything, suite included. Nothing is mandatory; this is the fast lane.
#
# What it runs — exactly the command CI's gate runs:
#
#   python -u -m pytest tests/unit -q \
#       -o faulthandler_timeout=120 -o faulthandler_exit_on_timeout=True
#
# (with --scope F: ... -k F), wrapped in `timeout --foreground 600`. Both
# bounds are measured, not guessed: the worst GREEN CI Test step was 41s
# (runs 35248848296, 35246056805, 35235114053 — all 41s) and this machine
# runs the whole suite in 32s, so a single test older than 120s and a step
# older than 600s are hangs, not slow tests. faulthandler names the hang
# (all-thread traceback, then exit 1); `timeout` is the backstop for a hang
# faulthandler's timer thread cannot observe.
#
# On success it writes .git/local-gate/<tree-sha>.ok (inside .git, so it is
# never committed) holding the tree, the timestamp, the scope, the counts
# parsed from pytest's summary line and the exact command. Re-running for the
# same tree is a no-op that just re-prints the trailer — the stamp IS the
# proof, so `--force` is the only way to pay for the suite twice.
#
# The trailer is printed only for a FULL run on a CLEAN tree: a --scope run
# is quick iteration, and a dirty tree cannot be described by a tree sha.
# Either one still prints the counts; it just makes no claim about a commit.
# A scoped run stamps .git/local-gate/<tree-sha>.<scope>.ok — its own file, so
# it can neither clobber the full-suite stamp nor be read back as one.
#
# Prerequisites: a virtualenv with CI's dependency set (see the recipe the
# script prints when something is missing). Checked first, so a mysterious
# failure 90 seconds in is not possible.
#
# Usage:
#   scripts/gate-local.sh                 # full gate (reuses a stamp if it exists)
#   scripts/gate-local.sh --force         # full gate, even if already stamped
#   scripts/gate-local.sh --scope eval    # quick iteration (pytest -k, no trailer)
#   scripts/gate-local.sh --amend         # full gate, then append the
#                                         # trailer to the HEAD commit
#
# Environment:
#   GATE_PYTHON         interpreter to use (default: .venv/bin/python)
#   GATE_STEP_TIMEOUT   shell bound for the suite, seconds (default: 600)
#   GATE_TEST_TIMEOUT   faulthandler per-test bound, seconds (default: 120)
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$here"

scope=""
amend=0
force=0
while [ $# -gt 0 ]; do
    case "$1" in
        --scope)
            [ $# -ge 2 ] || { echo "--scope needs a pytest -k filter (e.g. --scope eval)" >&2; exit 2; }
            scope=$2
            shift 2
            ;;
        --amend)
            amend=1
            shift
            ;;
        --force)
            force=1
            shift
            ;;
        -h|--help)
            sed -n '/^# Usage:/,/^# Environment:/p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "unknown argument: $1 (see --help)" >&2
            exit 2
            ;;
    esac
done

py=${GATE_PYTHON:-$here/.venv/bin/python}
step_timeout=${GATE_STEP_TIMEOUT:-600}
test_timeout=${GATE_TEST_TIMEOUT:-120}

# ── Record what this run is ─────────────────────────────────────────────────
tree=$(git rev-parse HEAD^{tree})
head=$(git rev-parse --short HEAD)
stamp_dir=$(git rev-parse --git-dir)/local-gate
mkdir -p "$stamp_dir"

if [ -n "$scope" ]; then
    scope_label=$scope
else
    scope_label=full
fi

# Stamps are keyed by tree AND scope. A scoped run gets its own file so it can
# never overwrite the full-suite stamp (the trailer is a claim about the whole
# suite, and the pre-push hook checks `scope: full`) — and never be mistaken
# for it on the next run.
if [ -n "$scope" ]; then
    safe_scope=${scope//[^A-Za-z0-9._-]/_}
    stamp=$stamp_dir/$tree.$safe_scope.ok
    log=$stamp_dir/$tree.$safe_scope.log
else
    stamp=$stamp_dir/$tree.ok
    log=$stamp_dir/$tree.log
fi

dirty=no
if [ -n "$(git status --porcelain)" ]; then
    dirty=yes
    cat <<'EOF'
WARNING: the working tree is dirty. The gate will test what is on disk, but a
         stamp can only describe a committed tree — so NO stamp and no trailer
         will be written this run. Commit, then re-run to get one.
EOF
fi

# The tail both paths share: print (and optionally amend in) the trailer.
emit_trailer() {
    if [ "$scope_label" != full ]; then
        cat <<EOF

== scoped run ($scope_label): no Local-Gate trailer.
   The trailer is a claim about the FULL suite, so only an unscoped run
   produces it. Re-run \`scripts/gate-local.sh\` before pushing if you want
   GitHub to skip its own suite.
EOF
        return 0
    fi
    local trailer="Local-Gate: $tree (${passed:-0} passed, ${seconds:-0}s)"
    if [ "$amend" = 1 ]; then
        if git branch -r --contains HEAD 2>/dev/null | grep -q .; then
            echo "REFUSING --amend: HEAD is already on a remote branch; amend would rewrite published history." >&2
            echo "Add the trailer by hand instead:" >&2
            echo "    $trailer" >&2
            exit 1
        fi
        local message
        message=$(git log -1 --format=%B)
        if printf '%s\n' "$message" | grep -q '^Local-Gate: '; then
            message=$(printf '%s\n' "$message" | sed "s|^Local-Gate: .*|$trailer|")
        else
            message=$(printf '%s\n' "$message" | sed -e :a -e '/^\n*$/{$d;N;ba' -e '}')
            message="$message
$trailer"
        fi
        printf '%s\n' "$message" | git commit --amend -q --no-verify -F -
        echo "== appended to $(git rev-parse --short HEAD) (tree unchanged: $(git rev-parse HEAD^{tree}))"
    fi
    cat <<EOF

Add this line to the commit you are about to push:

    $trailer

(\`scripts/gate-local.sh --amend\` appends it to HEAD for you — the tree does
not change, so an amend cannot invalidate the stamp.) The push then carries a
verified claim: the workflow's "Decide test gate" step compares the trailer's
tree with HEAD^{tree} and skips the runner suite only when they match.
EOF
}

# Already proven on this exact tree (and this scope): the stamp IS the
# evidence, so re-running the suite would only burn half a minute to arrive at
# the same line. A --scope request only ever matches its OWN stamp, so it can
# never be answered with (or overwrite) a full-suite proof.
if [ "$force" = 0 ] && [ "$dirty" = no ] && [ -f "$stamp" ]; then
    scope_label=$(sed -n 's/^scope: //p' "$stamp" | tail -1)
    passed=$(sed -n 's/^passed: //p' "$stamp" | tail -1)
    seconds=$(sed -n 's/^duration_seconds: //p' "$stamp" | tail -1)
    echo "== tree $tree already verified on this machine; reusing $stamp (--force to re-run)"
    cat "$stamp"
    emit_trailer
    exit 0
fi

# ── Prerequisites ───────────────────────────────────────────────────────────
# Each says what is missing and the exact command that fixes it: a mysterious
# failure 90 seconds in is worse than not starting.
[ -x "$py" ] || {
    cat >&2 <<EOF
No interpreter at $py — the gate runs CI's dependency set in a local venv:

    python3 -m venv --system-site-packages .venv
    .venv/bin/pip install -q -r requirements.txt -r requirements-eval.txt pytest

--system-site-packages reuses the system torch/FlagEmbedding
(requirements-local.txt) instead of downloading them. Point GATE_PYTHON at
another interpreter that already has everything if you keep the venv elsewhere.
EOF
    exit 1
}

missing=$("$py" - <<'PY'
import importlib.util, sys

mods = ["pytest", "deepeval", "fitz", "pdfplumber", "qdrant_client", "fastapi", "aioquic"]
gone = []
for name in mods:
    try:
        found = importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        found = False
    if not found:
        gone.append(name)
print(" ".join(gone))
PY
)
if [ -n "$missing" ]; then
    cat >&2 <<EOF
$py is missing modules the suite imports: $missing

Install CI's dependency set into that interpreter:

    .venv/bin/pip install -q -r requirements.txt -r requirements-eval.txt pytest

requirements-eval.txt is NOT optional: without deepeval five eval test modules
(error on import) break collection, and requirements.txt + pytest are the gate
itself. torch comes from --system-site-packages, not from pip.
EOF
    exit 1
fi

pytest_opts=(-o "faulthandler_timeout=$test_timeout" -o faulthandler_exit_on_timeout=True)

: > "$log"
echo "== tree $tree (HEAD $head), scope: $scope_label, log: $log"
echo "== interpreter: $py ($("$py" -c 'import sys; print(sys.version.split()[0])'))"

# ── The suite ───────────────────────────────────────────────────────────────
declare -a commands=()

run_step() {
    local label=$1
    shift
    commands+=("$(printf '%q ' "$@")")
    echo
    echo "=== $label"
    echo "+ $(printf '%q ' "$@")"
    if "$@" 2>&1 | tee -a "$log"; then
        echo "--- $label: OK"
    else
        local rc=$?
        if [ "$rc" = 124 ]; then
            echo "--- $label: TIMED OUT after ${step_timeout}s (exit 124) — the suite hung; the output above is everything it reached" >&2
        else
            echo "--- $label: FAILED (exit $rc) — nothing was stamped; fix it and re-run" >&2
        fi
        exit $rc
    fi
}

# The gate itself, byte for byte what CI's Test step runs (only the runner's
# bare `python` becomes this venv's interpreter). `timeout --foreground` keeps
# the process attached to this terminal and unbuffered: the progress dot line
# and the faulthandler dump survive the kill.
if [ -n "$scope" ]; then
    run_step "pytest (scope: $scope)" \
        timeout --foreground "$step_timeout" \
        "$py" -u -m pytest tests/unit -q -k "$scope" "${pytest_opts[@]}"
else
    run_step "pytest (full suite)" \
        timeout --foreground "$step_timeout" \
        "$py" -u -m pytest tests/unit -q "${pytest_opts[@]}"
fi

# ── Parse pytest's summary line ─────────────────────────────────────────────
# Shape: `1387 passed, 34 skipped, 32 warnings, 542 subtests passed in 32.31s`.
# The `(^|, )` anchor is what keeps "542 subtests passed" out of the `passed`
# count, and anchoring on the trailing `in Xs` picks the summary line rather
# than a test that printed a similar sentence.
summary=$(grep -E ' in [0-9][0-9.]*s$' "$log" | tail -1 || true)
if [ -z "$summary" ]; then
    summary=$(grep -E '^[0-9]+ (passed|failed|error)' "$log" | tail -1 || true)
fi
if [ -z "$summary" ]; then
    echo "no pytest summary line in $log — the counts are unknown, so no stamp is written" >&2
    exit 1
fi

# Every parse is `|| true`: "0 failed" simply does not appear in the summary
# line, and a bare `grep -oE` with no match exits 1 — which, under
# `set -e` + pipefail, would abort a run that passed.
field() {
    printf '%s\n' "$summary" | grep -oE "(^|, )[0-9]+ $1" | grep -oE '[0-9]+' | head -1 || true
}
passed=$(field passed)
skipped=$(field skipped)
failed=$(field failed)
errors=$(field error)
subtests=$(printf '%s\n' "$summary" | grep -oE '[0-9]+ subtests passed' | grep -oE '[0-9]+' | head -1 || true)
duration=$(printf '%s\n' "$summary" | grep -oE 'in [0-9][0-9.]*s' | grep -oE '[0-9][0-9.]*' | head -1 || true)
if [ -z "$passed" ]; then
    echo "could not read the counts out of: $summary" >&2
    exit 1
fi
seconds=${duration%%.*}
counts="$passed passed, ${failed:-0} failed, ${skipped:-0} skipped (${subtests:-0} subtests passed)"

echo
echo "== $summary"
echo "== counts: $counts (${seconds}s)"

if [ "$dirty" = yes ]; then
    echo "== no stamp written (dirty working tree); commit and re-run"
    exit 0
fi

# ── The stamp ───────────────────────────────────────────────────────────────
{
    echo "tree: $tree"
    echo "head: $head"
    echo "time: $(date -Is)"
    echo "scope: $scope_label"
    echo "dirty: $dirty"
    echo "counts: $counts"
    echo "passed: ${passed:-0}"
    echo "skipped: ${skipped:-0}"
    echo "failed: ${failed:-0}"
    echo "errors: ${errors:-0}"
    echo "duration_seconds: ${seconds:-0}"
    for command in "${commands[@]}"; do
        echo "command: ${command% }"
    done
} > "$stamp"

echo "== stamp: $stamp"
cat "$stamp"

emit_trailer
