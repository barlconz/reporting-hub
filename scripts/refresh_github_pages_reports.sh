#!/usr/bin/env bash
# Quarterly dashboard + Sprint Health + Dev Done risk → GitHub Pages snapshots.
# Used locally and by .github/workflows/github-pages-reports.yml
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python}"

STAGES=("quarterly" "sef" "sefk" "delivery-health" "site-index")
SELECTED_STAGES=()
EXTRA_ARGS=()
PREFLIGHT_ONLY=0

print_usage() {
	cat <<'EOF'
Usage: refresh_github_pages_reports.sh [options]

Options:
	--stage <name>        Run only one stage (repeatable).
	--list-stages         Print available stage names and exit.
	--preflight-only      Validate requested stages and environment, then exit.
	-h, --help            Show this help text.

Available stages:
	quarterly
	sef
	sefk
	delivery-health
	site-index
EOF
}

is_valid_stage() {
	local requested="$1"
	for stage in "${STAGES[@]}"; do
		if [[ "$stage" == "$requested" ]]; then
			return 0
		fi
	done
	return 1
}

while [[ $# -gt 0 ]]; do
	case "$1" in
		--stage)
			if [[ $# -lt 2 ]]; then
				echo "Missing value for --stage" >&2
				exit 2
			fi
			if ! is_valid_stage "$2"; then
				echo "Unknown stage: $2" >&2
				exit 2
			fi
			SELECTED_STAGES+=("$2")
			shift 2
			;;
		--list-stages)
			printf '%s\n' "${STAGES[@]}"
			exit 0
			;;
		--preflight-only)
			PREFLIGHT_ONLY=1
			shift
			;;
		-h|--help)
			print_usage
			exit 0
			;;
		*)
			EXTRA_ARGS+=("$1")
			shift
			;;
	esac
done

if [[ ${#SELECTED_STAGES[@]} -eq 0 ]]; then
	SELECTED_STAGES=("${STAGES[@]}")
fi

echo "Stages: ${SELECTED_STAGES[*]}"
if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
	echo "Forwarded args: ${EXTRA_ARGS[*]}"
fi

for stage in "${SELECTED_STAGES[@]}"; do
	case "$stage" in
		quarterly)
			[[ -f scripts/quarterly/refresh_dashboard_pages.sh ]] || {
				echo "Missing file: scripts/quarterly/refresh_dashboard_pages.sh" >&2
				exit 1
			}
			[[ -f scripts/quarterly/milestone_scope_report.py ]] || {
				echo "Missing file: scripts/quarterly/milestone_scope_report.py" >&2
				exit 1
			}
			;;
		sef)
			[[ -f scripts/sef/fetch_sef_project_plan_timeline.py ]] || {
				echo "Missing file: scripts/sef/fetch_sef_project_plan_timeline.py" >&2
				exit 1
			}
			;;
		sefk)
			[[ -f scripts/sefk/fetch_sefk_project_plan_timeline.py ]] || {
				echo "Missing file: scripts/sefk/fetch_sefk_project_plan_timeline.py" >&2
				exit 1
			}
			;;
		delivery-health)
			[[ -f scripts/refresh_delivery_health_pages.sh ]] || {
				echo "Missing file: scripts/refresh_delivery_health_pages.sh" >&2
				exit 1
			}
			;;
		site-index)
			[[ -f scripts/publish_github_pages_site_index.py ]] || {
				echo "Missing file: scripts/publish_github_pages_site_index.py" >&2
				exit 1
			}
			;;
	esac
done

echo "Preflight passed."
if [[ $PREFLIGHT_ONLY -eq 1 ]]; then
	echo "Preflight-only mode complete."
	exit 0
fi

for stage in "${SELECTED_STAGES[@]}"; do
	case "$stage" in
		quarterly)
			bash scripts/quarterly/refresh_dashboard_pages.sh "${EXTRA_ARGS[@]}"
			"$PY" scripts/quarterly/milestone_scope_report.py --output docs/quarter/milestone.html
			;;
		sef)
			"$PY" scripts/sef/fetch_sef_project_plan_timeline.py --write
			"$PY" scripts/sef/sef_project_plan_report.py --write
			"$PY" scripts/sef/publish_sef_test_plan_reports.py --write
			"$PY" scripts/sef/build_plan_959_test_cycles_report.py --write-mirror
			;;
		sefk)
			"$PY" scripts/sefk/fetch_sefk_project_plan_timeline.py --write
			"$PY" scripts/sefk/sefk_project_plan_report.py --write
			;;
		delivery-health)
			bash scripts/refresh_delivery_health_pages.sh "${EXTRA_ARGS[@]}"
			;;
		site-index)
			"$PY" scripts/github_copilot_governance_summary.py
			"$PY" scripts/publish_github_pages_site_index.py
			;;
	esac
done
