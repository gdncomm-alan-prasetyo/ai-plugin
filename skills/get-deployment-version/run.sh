#!/usr/bin/env bash
# Usage: bash run.sh [normal|canary|both]
MODE="${1:-normal}"

# Jira project key used in the Fix Version links below.
JIRA_PROJECT="${JIRA_PROJECT:-IAM}"

TMPDIR=$(mktemp -d)

OWNER="gdncomm"

# One entry per service: "Display Name|nonprod-repo|prod-repo|canary-nonprod-repo|canary-prod-repo"
# nonprod-repo branches: qa2, preprod (+ canary-qa2, canary-preprod when canary is branch-based)
# prod-repo branches:    master (+ canary-prod when canary is branch-based)
#
# The last two fields are optional and control how canary is fetched (canary layout varies per service):
#   - omitted/empty  → branch-based canary (default): canary comes from the SAME repo, on the
#                       canary-qa2/canary-preprod/canary-prod branches.
#   - "NONE"         → this service has no canary environment at all (e.g. IAM RBAC). Canary mode
#                       skips it entirely rather than reporting a false Fetch Error.
#   - a repo name     → repo-based canary: canary lives in a SEPARATE deployment repo (e.g. a
#                       "-next" sibling, as with pyeongyang-member/pyeongyang-member-reward). That
#                       repo already IS the canary variant, so it's read on its own qa2/preprod/master
#                       branches (no canary- prefix) rather than canary-qa2/canary-preprod/canary-prod.
repos=(
  "Member|nonprod-deployment-gdn-member|prod-deployment-gdn-member"
  "Auth|nonprod-deployment-gdn-auth|prod-deployment-gdn-auth"
  "IAM API|nonprod-deployment-gdn-iam-api|prod-deployment-gdn-iam-api"
  "IAM Session Manager|nonprod-deployment-gdn-iam-session-manager|prod-deployment-gdn-iam-session-manager"
  "IAM RBAC|nonprod-deployment-gdn-iam-rbac|prod-deployment-gdn-iam-rbac|NONE|NONE"
)

fetch_version() {
  local repo="$1" branch="$2" outfile="$3"
  local file_path="deployment/values.yaml"
  local raw_output exit_code
  raw_output=$(gh api "repos/${OWNER}/${repo}/contents/${file_path}?ref=${branch}" --jq '.content' 2>&1)
  exit_code=$?
  if [ $exit_code -ne 0 ]; then
    if echo "$raw_output" | grep -qi "not found\|404"; then echo "NOT_FOUND" > "$outfile"
    else echo "ERROR" > "$outfile"; fi
    return
  fi
  local tag
  tag=$(echo "$raw_output" | base64 -d 2>/dev/null | grep -E '^\s*tag:' | head -1 | sed 's/.*tag:\s*//' | tr -d '"' | tr -d "'" | tr -d ' ')
  if [ -z "$tag" ]; then echo "NOT_FOUND" > "$outfile"
  else echo "$tag" > "$outfile"; fi
}

# Launch fetches in parallel based on mode
# Normal pipeline: qa2 + preprod come from the nonprod repo, master (prod) from the prod repo.
# Canary pipeline: layout-dependent per entry — see the repos[] comment above.
for entry in "${repos[@]}"; do
  IFS='|' read -r name nonprod_repo prod_repo canary_nonprod_repo canary_prod_repo <<< "$entry"
  safe_name=$(echo "$name" | tr ' ' '_')
  if [ "$MODE" = "normal" ] || [ "$MODE" = "both" ]; then
    fetch_version "$nonprod_repo" "qa2"     "${TMPDIR}/${safe_name}_qa2"     &
    fetch_version "$nonprod_repo" "preprod" "${TMPDIR}/${safe_name}_preprod" &
    fetch_version "$prod_repo"    "master"  "${TMPDIR}/${safe_name}_prod"    &
  fi
  if [ "$MODE" = "canary" ] || [ "$MODE" = "both" ]; then
    if [ "$canary_nonprod_repo" = "NONE" ]; then
      echo "N/A" > "${TMPDIR}/${safe_name}_canary_qa2"
      echo "N/A" > "${TMPDIR}/${safe_name}_canary_preprod"
    elif [ -n "$canary_nonprod_repo" ]; then
      # Repo-based canary: separate repo, read on its own qa2/preprod branches (no canary- prefix).
      fetch_version "$canary_nonprod_repo" "qa2"     "${TMPDIR}/${safe_name}_canary_qa2"     &
      fetch_version "$canary_nonprod_repo" "preprod" "${TMPDIR}/${safe_name}_canary_preprod" &
    else
      # Branch-based canary (default): same repo, canary-qa2/canary-preprod branches.
      fetch_version "$nonprod_repo" "canary-qa2"     "${TMPDIR}/${safe_name}_canary_qa2"     &
      fetch_version "$nonprod_repo" "canary-preprod" "${TMPDIR}/${safe_name}_canary_preprod" &
    fi
    if [ "$canary_prod_repo" = "NONE" ]; then
      echo "N/A" > "${TMPDIR}/${safe_name}_canary_prod"
    elif [ -n "$canary_prod_repo" ]; then
      fetch_version "$canary_prod_repo" "master" "${TMPDIR}/${safe_name}_canary_prod" &
    else
      fetch_version "$prod_repo" "canary-prod" "${TMPDIR}/${safe_name}_canary_prod" &
    fi
  fi
done
wait

version_gt() { [ "$(printf '%s\n' "$1" "$2" | sort -V | tail -1)" = "$1" ] && [ "$1" != "$2" ]; }

compute_status() {
  local d="$1" q="$2" p="$3"
  if echo "$d $q $p" | grep -qE 'N/A'; then echo "No Canary"
  elif echo "$d $q $p" | grep -qE 'NOT_FOUND|ERROR'; then echo "Fetch Error"
  elif [ "$d" = "$q" ] && [ "$q" = "$p" ]; then echo "All Sync"
  elif [ "$d" != "$q" ] && [ "$q" != "$p" ]; then echo "Ready for Prod"
  elif [ "$d" != "$q" ]; then echo "Ready for Preprod"
  else
    if version_gt "$p" "$q" 2>/dev/null; then echo "Prod Newer"
    else echo "Ready for Prod"; fi
  fi
}

status_order() {
  case "$1" in
    "Ready for Preprod") echo 1 ;;
    "Ready for Prod")    echo 2 ;;
    "All Sync")          echo 3 ;;
    "Prod Newer")        echo 4 ;;
    "Fetch Error")       echo 5 ;;
    "No Canary")         echo 6 ;;
    *)                   echo 9 ;;
  esac
}

status_icon() {
  case "$1" in
    "All Sync")          echo "✅" ;;
    "Ready for Preprod") echo "🔵" ;;
    "Ready for Prod")    echo "🟡" ;;
    "Prod Newer")        echo "🔴" ;;
    "No Canary")         echo "⚪" ;;
    *)                   echo "⚠️" ;;
  esac
}

collect_rows() {
  local suffix_d="$1" suffix_q="$2" suffix_p="$3"
  for entry in "${repos[@]}"; do
    IFS='|' read -r name nonprod_repo prod_repo <<< "$entry"
    safe_name=$(echo "$name" | tr ' ' '_')
    dev_ver=$(cat "${TMPDIR}/${safe_name}_${suffix_d}" 2>/dev/null || echo "ERROR")
    qa_ver=$(cat  "${TMPDIR}/${safe_name}_${suffix_q}" 2>/dev/null || echo "ERROR")
    prd_ver=$(cat "${TMPDIR}/${safe_name}_${suffix_p}" 2>/dev/null || echo "ERROR")
    st=$(compute_status "$dev_ver" "$qa_ver" "$prd_ver")
    ord=$(status_order "$st")
    echo "${ord}|${name}|${dev_ver}|${qa_ver}|${prd_ver}|${st}"
  done | sort -t'|' -k1,1n
}

render_table() {
  local rows="$1"
  local -a rs rd rq rp rst
  while IFS='|' read -r ord name dev qa prd st; do
    rs+=("$name"); rd+=("$dev"); rq+=("$qa"); rp+=("$prd"); rst+=("$st")
  done <<< "$rows"

  local w_svc=7 w_dev=4 w_qa=7 w_prd=4 w_st=6
  for i in "${!rs[@]}"; do
    local st_full
    st_full="$(status_icon "${rst[$i]}") ${rst[$i]}"
    [ ${#rs[$i]}  -gt $w_svc ] && w_svc=${#rs[$i]}
    [ ${#rd[$i]}  -gt $w_dev ] && w_dev=${#rd[$i]}
    [ ${#rq[$i]}  -gt $w_qa  ] && w_qa=${#rq[$i]}
    [ ${#rp[$i]}  -gt $w_prd ] && w_prd=${#rp[$i]}
    [ ${#st_full} -gt $w_st  ] && w_st=${#st_full}
  done

  local ds_svc ds_dev ds_qa ds_prd ds_st
  ds_svc=$(printf '%0.s-' $(seq 1 $w_svc))
  ds_dev=$(printf '%0.s-' $(seq 1 $w_dev))
  ds_qa=$(printf  '%0.s-' $(seq 1 $w_qa))
  ds_prd=$(printf '%0.s-' $(seq 1 $w_prd))
  ds_st=$(printf  '%0.s-' $(seq 1 $w_st))

  printf "| %-${w_svc}s | %-${w_dev}s | %-${w_qa}s | %-${w_prd}s | %-${w_st}s |\n" "Service" "QA2" "PREPROD" "PROD" "Status"
  printf "|-%-${w_svc}s-|-%-${w_dev}s-|-%-${w_qa}s-|-%-${w_prd}s-|-%-${w_st}s-|\n" "$ds_svc" "$ds_dev" "$ds_qa" "$ds_prd" "$ds_st" | tr ' ' '-'
  for i in "${!rs[@]}"; do
    local st_full
    st_full="$(status_icon "${rst[$i]}") ${rst[$i]}"
    printf "| %-${w_svc}s | %-${w_dev}s | %-${w_qa}s | %-${w_prd}s | %s |\n" "${rs[$i]}" "${rd[$i]}" "${rq[$i]}" "${rp[$i]}" "${st_full}"
  done
}

build_action_items() {
  local rows="$1"
  while IFS='|' read -r ord name dev qa prd st; do
    case "$st" in
      "Ready for Preprod") echo "- **${name}**: promote \`${dev}\` QA2 → PREPROD" ;;
      "Ready for Prod")    echo "- **${name}**: promote \`${qa}\` PREPROD → PROD" ;;
      "Prod Newer")        echo "- **${name}**: ⚠️ PROD (\`${prd}\`) is ahead of PREPROD (\`${qa}\`) — investigate" ;;
    esac
  done <<< "$rows"
}

build_jira_links() {
  local rows="$1"
  while IFS='|' read -r ord name dev qa prd st; do
    local ver enc_name label url
    if [ "$st" = "Ready for Preprod" ]; then
      ver="${dev%-*}"
    elif [ "$st" = "Ready for Prod" ]; then
      ver="${qa%-*}"
    else
      continue
    fi
    enc_name="${name// /%20}"
    label="${name} ${ver}"
    url="https://gdncomm.atlassian.net/issues?jql=project%20%3D%20${JIRA_PROJECT}%20AND%20fixversion%20%3D%20%22${enc_name}%20${ver}%22%20ORDER%20BY%20updated%20DESC"
    echo "- [${label}](${url})"
  done <<< "$rows"
}

count_status() {
  echo "$1" | awk -F'|' -v t="$2" '$6==t' | wc -l | tr -d ' '
}

# Collect rows per pipeline
if [ "$MODE" = "normal" ] || [ "$MODE" = "both" ]; then
  normal_rows=$(collect_rows "qa2" "preprod" "prod")
fi
if [ "$MODE" = "canary" ] || [ "$MODE" = "both" ]; then
  canary_rows=$(collect_rows "canary_qa2" "canary_preprod" "canary_prod")
fi

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

echo "# Deployment Version Comparison"
echo "_Generated: ${TIMESTAMP}_"
echo ""

if [ "$MODE" = "normal" ] || [ "$MODE" = "both" ]; then
  echo "## Normal Pipeline"
  echo ""
  render_table "$normal_rows"
  echo ""
fi

if [ "$MODE" = "canary" ] || [ "$MODE" = "both" ]; then
  echo "## Canary Pipeline"
  echo ""
  render_table "$canary_rows"
  echo ""
fi

echo "## Summary"
echo ""
if [ "$MODE" = "both" ]; then
  printf "| %-20s | %-6s | %-6s |\n" "Metric" "Normal" "Canary"
  printf "|-%-20s-|-%-6s-|-%-6s-|\n" "--------------------" "------" "------" | tr ' ' '-'
  printf "| %-20s | %-6s | %-6s |\n" "Total services"      "$(echo "$normal_rows" | wc -l | tr -d ' ')" "$(echo "$canary_rows" | wc -l | tr -d ' ')"
  printf "| %-20s | %-6s | %-6s |\n" "🔵 Ready for Preprod" "$(count_status "$normal_rows" "Ready for Preprod")" "$(count_status "$canary_rows" "Ready for Preprod")"
  printf "| %-20s | %-6s | %-6s |\n" "🟡 Ready for Prod"    "$(count_status "$normal_rows" "Ready for Prod")"    "$(count_status "$canary_rows" "Ready for Prod")"
  printf "| %-20s | %-6s | %-6s |\n" "✅ All Sync"          "$(count_status "$normal_rows" "All Sync")"          "$(count_status "$canary_rows" "All Sync")"
  printf "| %-20s | %-6s | %-6s |\n" "🔴 Prod Newer"        "$(count_status "$normal_rows" "Prod Newer")"        "$(count_status "$canary_rows" "Prod Newer")"
  printf "| %-20s | %-6s | %-6s |\n" "⚠️ Fetch Errors"     "$(count_status "$normal_rows" "Fetch Error")"       "$(count_status "$canary_rows" "Fetch Error")"
  printf "| %-20s | %-6s | %-6s |\n" "⚪ No Canary"         "$(count_status "$normal_rows" "No Canary")"         "$(count_status "$canary_rows" "No Canary")"
else
  rows_ref="${normal_rows:-$canary_rows}"
  printf "| %-20s | %-6s |\n" "Metric" "Count"
  printf "|-%-20s-|-%-6s-|\n" "--------------------" "------" | tr ' ' '-'
  printf "| %-20s | %-6s |\n" "Total services"      "$(echo "$rows_ref" | wc -l | tr -d ' ')"
  printf "| %-20s | %-6s |\n" "🔵 Ready for Preprod" "$(count_status "$rows_ref" "Ready for Preprod")"
  printf "| %-20s | %-6s |\n" "🟡 Ready for Prod"    "$(count_status "$rows_ref" "Ready for Prod")"
  printf "| %-20s | %-6s |\n" "✅ All Sync"          "$(count_status "$rows_ref" "All Sync")"
  printf "| %-20s | %-6s |\n" "🔴 Prod Newer"        "$(count_status "$rows_ref" "Prod Newer")"
  printf "| %-20s | %-6s |\n" "⚠️ Fetch Errors"     "$(count_status "$rows_ref" "Fetch Error")"
  printf "| %-20s | %-6s |\n" "⚪ No Canary"         "$(count_status "$rows_ref" "No Canary")"
fi
echo ""

# Action Items
n_acts=""; c_acts=""
[ -n "$normal_rows" ] && n_acts=$(build_action_items "$normal_rows")
[ -n "$canary_rows" ] && c_acts=$(build_action_items "$canary_rows")
if [ -n "$n_acts" ] || [ -n "$c_acts" ]; then
  echo "## Action Items"
  echo ""
  if [ -n "$n_acts" ]; then
    [ "$MODE" = "both" ] && echo "**Normal Pipeline:**"
    echo "$n_acts"
    echo ""
  fi
  if [ -n "$c_acts" ]; then
    [ "$MODE" = "both" ] && echo "**Canary Pipeline:**"
    echo "$c_acts"
    echo ""
  fi
fi

# Jira Fix Version Links
n_jira=""; c_jira=""
[ -n "$normal_rows" ] && n_jira=$(build_jira_links "$normal_rows")
[ -n "$canary_rows" ] && c_jira=$(build_jira_links "$canary_rows")
if [ -n "$n_jira" ] || [ -n "$c_jira" ]; then
  echo "## Jira Fix Version Links"
  echo ""
  if [ -n "$n_jira" ]; then
    [ "$MODE" = "both" ] && echo "**Normal Pipeline:**"
    echo "$n_jira"
    echo ""
  fi
  if [ -n "$c_jira" ]; then
    [ "$MODE" = "both" ] && echo "**Canary Pipeline:**"
    echo "$c_jira"
  fi
fi

rm -rf "$TMPDIR"
