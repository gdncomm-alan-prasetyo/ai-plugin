#!/bin/bash

# Get Deployment Version Checker
# Compares deployment versions between dev, qa, and prod environments (with optional canary)

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
CONFIG_FILE="$SCRIPT_DIR/config.yml"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Check if config file exists
if [[ ! -f "$CONFIG_FILE" ]]; then
    echo -e "${RED}❌ Error: config.yml not found${NC}"
    echo "Please create config.yml with your repository configuration."
    exit 1
fi

# Extract repos from config using awk
extract_repos() {
    local file=$1
    awk '
    /^repos:/ { in_repos=1; next }
    in_repos && /^  - name:/ && !/^  *#/ {
        if (name != "" && owner != "" && repo != "") {
            print name "|" owner "|" repo
        }
        name=$0; sub(/^  - name: /, "", name); gsub(/"/, "", name)
        owner=""; repo=""
        next
    }
    in_repos && /^    owner:/ && !/^    *#/ {
        owner=$0; sub(/^    owner: /, "", owner); gsub(/"/, "", owner)
        next
    }
    in_repos && /^    repo:/ && !/^    *#/ {
        repo=$0; sub(/^    repo: /, "", repo); gsub(/"/, "", repo)
        next
    }
    in_repos && /^[^ ]/ && !/^repos:/ {
        if (name != "" && owner != "" && repo != "") {
            print name "|" owner "|" repo
        }
        in_repos=0
        name=""; owner=""; repo=""
    }
    END {
        if (name != "" && owner != "" && repo != "") {
            print name "|" owner "|" repo
        }
    }
    ' "$file"
}

# Fetch version from GitHub
fetch_version() {
    local owner=$1
    local repo=$2
    local branch=$3
    local file_path=$4
    local tag_key=$5

    # Replace {branch} placeholder in file_path
    local actual_path="$file_path"
    actual_path="${actual_path//\{branch\}/$branch}"

    local response
    response=$(gh api repos/"$owner"/"$repo"/contents/"$actual_path"?ref="$branch" --jq .content 2>/dev/null || echo "ERROR")

    if [[ "$response" == "ERROR" ]]; then
        echo "FETCH_ERROR"
        return 1
    fi

    # Decode base64 and extract tag
    local tag_value
    tag_value=$(echo "$response" | base64 -d 2>/dev/null | grep -E "^\s*$tag_key\s*:" | awk -F': ' '{gsub(/["'"'"']|#.*/,"",$2); gsub(/^\s+|\s+$/,"",$2); print $2; exit}')

    if [[ -z "$tag_value" ]]; then
        echo "TAG_NOT_FOUND"
        return 1
    fi

    echo "$tag_value"
}

# Compare versions (semantic versioning aware)
compare_versions() {
    local dev_version=$1
    local prod_version=$2

    if [[ "$dev_version" == "$prod_version" ]]; then
        echo "sync"
    else
        # Use sort -V for semantic version comparison
        local sorted
        sorted=$(printf '%s\n%s\n' "$dev_version" "$prod_version" | sort -V | head -1)
        if [[ "$sorted" == "$prod_version" ]]; then
            echo "needs_deploy"
        else
            echo "prod_newer"
        fi
    fi
}

# Get status emoji
get_status_emoji() {
    local status=$1
    case "$status" in
        sync)
            echo "✅ All Sync"
            ;;
        dev_ready)
            echo "🔄 Ready for QA"
            ;;
        qa_ready)
            echo "⚠️  Ready for Prod"
            ;;
        prod_newer)
            echo "⬇️  Prod Newer"
            ;;
        *)
            echo "❌ Fetch Error"
            ;;
    esac
}

# Read config in single pass
read_config() {
    local dev_br qa_br prod_br dev_can qa_can prod_can file_p tag_k gen_rep
    while IFS=': ' read -r key value; do
        # Remove comment if exists
        value="${value%% #*}"
        value="${value//[[:space:]]/}"

        [[ "$key" == "dev_branch" ]] && dev_br="$value"
        [[ "$key" == "qa_branch" ]] && qa_br="$value"
        [[ "$key" == "prod_branch" ]] && prod_br="$value"
        [[ "$key" == "dev_canary_branch" ]] && dev_can="$value"
        [[ "$key" == "qa_canary_branch" ]] && qa_can="$value"
        [[ "$key" == "prod_canary_branch" ]] && prod_can="$value"
        [[ "$key" == "file_path" ]] && file_p="$value"
        [[ "$key" == "tag_key" ]] && tag_k="$value"
        [[ "$key" == "generate_report" ]] && gen_rep="$value"
    done < "$CONFIG_FILE"

    echo "${dev_br:-dev}|${qa_br:-qa}|${prod_br:-prd}|${dev_can:-dev-canary}|${qa_can:-qa-canary}|${prod_can:-prd-canary}|${file_p:-deployment/values.yaml}|${tag_k:-tag}|${gen_rep:-true}"
}

# Main execution
main() {
    # Parse arguments
    local skip_canary=false
    local skip_normal=false

    if [[ "$1" == "normal" ]]; then
        skip_canary=true
    elif [[ "$1" == "canary" ]]; then
        skip_normal=true
    fi

    # Read config (single pass)
    local dev_branch qa_branch prod_branch dev_canary qa_canary prod_canary file_path tag_key generate_report
    IFS='|' read -r dev_branch qa_branch prod_branch dev_canary qa_canary prod_canary file_path tag_key generate_report < <(read_config)

    # Generate report filename if enabled
    local report_file=""
    local output_text=""
    if [[ "$generate_report" == "true" ]]; then
        local timestamp=$(date +%Y%m%d-%H%M%S)
        report_file="report-deployment-version-$timestamp.md"
    fi

    # Arrays to store results (normal and canary)
    declare -a results_normal
    declare -a results_canary
    declare -a needs_deploy_normal
    declare -a needs_deploy_canary
    local synced_normal=0 errors_normal=0
    local synced_canary=0 errors_canary=0
    local repo_count_normal=0 repo_count_canary=0

    # Extract repos
    local repos
    repos=$(extract_repos "$CONFIG_FILE")

    if [[ -z "$repos" ]]; then
        echo -e "${RED}❌ No repositories found in config.yml${NC}"
        exit 1
    fi

    # Count repos
    local total_repos
    total_repos=$(echo "$repos" | wc -l)

    output_text+="🔍 Fetching deployment versions from $total_repos repositories...\n\n"
    echo -e "${BLUE}🔍 Fetching deployment versions from $total_repos repositories...${NC}\n"

    # Process each repo with normal and canary branches
    while IFS='|' read -r name owner repo_name; do
        # Trim whitespace
        name="${name#"${name%%[![:space:]]*}"}"
        name="${name%"${name##*[![:space:]]}"}"
        owner="${owner#"${owner%%[![:space:]]*}"}"
        owner="${owner%"${owner##*[![:space:]]}"}"
        repo_name="${repo_name#"${repo_name%%[![:space:]]*}"}"
        repo_name="${repo_name%"${repo_name##*[![:space:]]}"}"

        # Fetch NORMAL versions in parallel (dev, qa, prod)
        fetch_version "$owner" "$repo_name" "$dev_branch" "$file_path" "$tag_key" > /tmp/dev_ver_$$ &
        local dev_pid=$!
        fetch_version "$owner" "$repo_name" "$qa_branch" "$file_path" "$tag_key" > /tmp/qa_ver_$$ &
        local qa_pid=$!
        fetch_version "$owner" "$repo_name" "$prod_branch" "$file_path" "$tag_key" > /tmp/prod_ver_$$ &
        local prod_pid=$!

        local dev_can_pid="" qa_can_pid="" prod_can_pid=""

        # Fetch CANARY versions in parallel (dev-canary, qa-canary, prd-canary) only if not skipped
        if [[ "$skip_canary" != "true" ]]; then
            fetch_version "$owner" "$repo_name" "$dev_canary" "$file_path" "$tag_key" > /tmp/dev_can_ver_$$ &
            dev_can_pid=$!
            fetch_version "$owner" "$repo_name" "$qa_canary" "$file_path" "$tag_key" > /tmp/qa_can_ver_$$ &
            qa_can_pid=$!
            fetch_version "$owner" "$repo_name" "$prod_canary" "$file_path" "$tag_key" > /tmp/prod_can_ver_$$ &
            prod_can_pid=$!
        fi

        # Wait for NORMAL fetches to complete
        wait $dev_pid $qa_pid $prod_pid 2>/dev/null
        # Wait for CANARY fetches if started
        if [[ -n "$dev_can_pid" ]]; then
            wait $dev_can_pid $qa_can_pid $prod_can_pid 2>/dev/null
        fi

        local dev_version qa_version prod_version dev_can_version qa_can_version prod_can_version
        dev_version=$(cat /tmp/dev_ver_$$)
        qa_version=$(cat /tmp/qa_ver_$$)
        prod_version=$(cat /tmp/prod_ver_$$)

        # Only read canary versions if they were fetched
        if [[ "$skip_canary" != "true" ]]; then
            dev_can_version=$(cat /tmp/dev_can_ver_$$)
            qa_can_version=$(cat /tmp/qa_can_ver_$$)
            prod_can_version=$(cat /tmp/prod_can_ver_$$)
        fi

        rm -f /tmp/dev_ver_$$ /tmp/qa_ver_$$ /tmp/prod_ver_$$ /tmp/dev_can_ver_$$ /tmp/qa_can_ver_$$ /tmp/prod_can_ver_$$

        # Process NORMAL versions
        local status dev_to_qa_status qa_to_prod_status
        if [[ "$dev_version" =~ ERROR|FETCH_ERROR|DECODE_ERROR|TAG_NOT_FOUND ]]; then
            status="error"
            dev_version="ERROR"
            ((errors_normal++))
        elif [[ "$qa_version" =~ ERROR|FETCH_ERROR|DECODE_ERROR|TAG_NOT_FOUND ]]; then
            status="error"
            qa_version="ERROR"
            ((errors_normal++))
        elif [[ "$prod_version" =~ ERROR|FETCH_ERROR|DECODE_ERROR|TAG_NOT_FOUND ]]; then
            status="error"
            prod_version="ERROR"
            ((errors_normal++))
        else
            dev_to_qa_status=$(compare_versions "$dev_version" "$qa_version")
            qa_to_prod_status=$(compare_versions "$qa_version" "$prod_version")

            if [[ "$dev_version" == "$qa_version" && "$qa_version" == "$prod_version" ]]; then
                status="sync"
                ((synced_normal++))
            elif [[ "$qa_to_prod_status" == "needs_deploy" ]]; then
                status="qa_ready"
                needs_deploy_normal+=("$name|qa->prod|$qa_version→$prod_version")
            elif [[ "$dev_to_qa_status" == "needs_deploy" ]]; then
                status="dev_ready"
                needs_deploy_normal+=("$name|dev->qa|$dev_version→$qa_version")
            else
                status="sync"
                ((synced_normal++))
            fi
        fi

        local status_emoji
        status_emoji=$(get_status_emoji "$status")
        results_normal+=("$name|$dev_version|$qa_version|$prod_version|$status_emoji")
        ((repo_count_normal++))

        # Process CANARY versions only if not skipped
        if [[ "$skip_canary" != "true" ]]; then
            if [[ "$dev_can_version" =~ ERROR|FETCH_ERROR|DECODE_ERROR|TAG_NOT_FOUND ]]; then
                status="error"
                dev_can_version="ERROR"
                ((errors_canary++))
            elif [[ "$qa_can_version" =~ ERROR|FETCH_ERROR|DECODE_ERROR|TAG_NOT_FOUND ]]; then
                status="error"
                qa_can_version="ERROR"
                ((errors_canary++))
            elif [[ "$prod_can_version" =~ ERROR|FETCH_ERROR|DECODE_ERROR|TAG_NOT_FOUND ]]; then
                status="error"
                prod_can_version="ERROR"
                ((errors_canary++))
            else
                dev_to_qa_status=$(compare_versions "$dev_can_version" "$qa_can_version")
                qa_to_prod_status=$(compare_versions "$qa_can_version" "$prod_can_version")

                if [[ "$dev_can_version" == "$qa_can_version" && "$qa_can_version" == "$prod_can_version" ]]; then
                    status="sync"
                    ((synced_canary++))
                elif [[ "$qa_to_prod_status" == "needs_deploy" ]]; then
                    status="qa_ready"
                    needs_deploy_canary+=("$name|qa->prod|$qa_can_version→$prod_can_version")
                elif [[ "$dev_to_qa_status" == "needs_deploy" ]]; then
                    status="dev_ready"
                    needs_deploy_canary+=("$name|dev->qa|$dev_can_version→$qa_can_version")
                else
                    status="sync"
                    ((synced_canary++))
                fi
            fi

            status_emoji=$(get_status_emoji "$status")
            results_canary+=("$name|$dev_can_version|$qa_can_version|$prod_can_version|$status_emoji")
            ((repo_count_canary++))
        fi

    done <<< "$repos"

    # Display NORMAL table (only if not skipped)
    if [[ "$skip_normal" != "true" ]]; then
        echo -e "${CYAN}📦 Normal Deployment Pipeline${NC}"
        echo "| Repository      | Dev Version    | QA Version     | Prod Version   | Status          |"
        echo "|-----------------|----------------|----------------|----------------|-----------------|"
        output_text+="## Normal Deployment Pipeline\n\n"
        output_text+="| Repository      | Dev Version    | QA Version     | Prod Version   | Status          |\n"
        output_text+="|-----------------|----------------|----------------|----------------|-------------------|\n"

        for result in "${results_normal[@]}"; do
            IFS='|' read -r name dev_ver qa_ver prod_ver status_emoji <<< "$result"
            printf "| %-15s | %-14s | %-14s | %-14s | %-15s |\n" "$name" "$dev_ver" "$qa_ver" "$prod_ver" "$status_emoji"
            output_text+="| $(printf '%-15s | %-14s | %-14s | %-14s | %-15s' "$name" "$dev_ver" "$qa_ver" "$prod_ver" "$status_emoji") |\n"
        done

        echo ""
        output_text+="\n"
    fi

    # Display CANARY table (only if not skipped)
    if [[ "$skip_canary" != "true" && ${#results_canary[@]} -gt 0 ]]; then
        echo -e "${CYAN}🔴 Canary Deployment Pipeline${NC}"
        echo "| Repository      | Dev Version    | QA Version     | Prod Version   | Status          |"
        echo "|-----------------|----------------|----------------|----------------|-----------------|"
        output_text+="\n## Canary Deployment Pipeline\n\n"
        output_text+="| Repository      | Dev Version    | QA Version     | Prod Version   | Status          |\n"
        output_text+="|-----------------|----------------|----------------|----------------|-------------------|\n"

        for result in "${results_canary[@]}"; do
            IFS='|' read -r name dev_ver qa_ver prod_ver status_emoji <<< "$result"
            printf "| %-15s | %-14s | %-14s | %-14s | %-15s |\n" "$name" "$dev_ver" "$qa_ver" "$prod_ver" "$status_emoji"
            output_text+="| $(printf '%-15s | %-14s | %-14s | %-14s | %-15s' "$name" "$dev_ver" "$qa_ver" "$prod_ver" "$status_emoji") |\n"
        done

        echo ""
        output_text+="\n"
    fi

    # Summary
    echo -e "${BLUE}📊 Summary:${NC}"
    if [[ "$skip_normal" != "true" ]]; then
        echo "- Normal repos   : $repo_count_normal (Synced: $synced_normal, Errors: $errors_normal)"
    fi
    if [[ "$skip_canary" != "true" ]]; then
        echo "- Canary repos   : $repo_count_canary (Synced: $synced_canary, Errors: $errors_canary)"
    fi

    if [[ "$skip_canary" != "true" && "$skip_normal" != "true" ]]; then
        echo "- Need Promotion : $((${#needs_deploy_normal[@]} + ${#needs_deploy_canary[@]}))"
    elif [[ "$skip_canary" == "true" ]]; then
        echo "- Need Promotion : ${#needs_deploy_normal[@]}"
    elif [[ "$skip_normal" == "true" ]]; then
        echo "- Need Promotion : ${#needs_deploy_canary[@]}"
    fi

    output_text+="\n## Summary\n\n"
    if [[ "$skip_normal" != "true" ]]; then
        output_text+="- Normal repos   : $repo_count_normal (Synced: $synced_normal, Errors: $errors_normal)\n"
    fi
    if [[ "$skip_canary" != "true" ]]; then
        output_text+="- Canary repos   : $repo_count_canary (Synced: $synced_canary, Errors: $errors_canary)\n"
    fi
    if [[ "$skip_canary" != "true" && "$skip_normal" != "true" ]]; then
        output_text+="- Need Promotion : $((${#needs_deploy_normal[@]} + ${#needs_deploy_canary[@]}))\n\n"
    elif [[ "$skip_canary" == "true" ]]; then
        output_text+="- Need Promotion : ${#needs_deploy_normal[@]}\n\n"
    elif [[ "$skip_normal" == "true" ]]; then
        output_text+="- Need Promotion : ${#needs_deploy_canary[@]}\n\n"
    fi

    # Show repositories needing promotion (Normal) - only if not skipped
    if [[ "$skip_normal" != "true" && ${#needs_deploy_normal[@]} -gt 0 ]]; then
        echo ""
        echo -e "${YELLOW}🚀 Normal: Repositories needing promotion:${NC}"
        output_text+="\n## Normal: Repositories Needing Promotion\n\n"
        for item in "${needs_deploy_normal[@]}"; do
            IFS='|' read -r name transition versions <<< "$item"
            echo "  • $name  ($transition: $versions)"
            output_text+="- $name ($transition: $versions)\n"
        done
    fi

    # Show repositories needing promotion (Canary) - only if not skipped
    if [[ "$skip_normal" != "true" && ${#needs_deploy_canary[@]} -gt 0 ]]; then
        echo ""
        echo -e "${YELLOW}🚀 Canary: Repositories needing promotion:${NC}"
        output_text+="\n## Canary: Repositories Needing Promotion\n\n"
        for item in "${needs_deploy_canary[@]}"; do
            IFS='|' read -r name transition versions <<< "$item"
            echo "  • $name  ($transition: $versions)"
            output_text+="- $name ($transition: $versions)\n"
        done
    fi

    echo ""

    # Generate report file if enabled
    if [[ "$generate_report" == "true" && -n "$report_file" ]]; then
        # Prepare report header
        local report_content="# Deployment Version Report\n\n"
        report_content+="Generated: $(date '+%Y-%m-%d %H:%M:%S')\n\n"
        report_content+="$output_text"

        # Write to file
        echo -e "$report_content" > "$report_file"
        echo -e "${GREEN}✅ Report saved: $report_file${NC}"
    fi
}

main "$@"
