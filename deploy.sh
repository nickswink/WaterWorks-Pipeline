#!/usr/bin/env bash
#
# deploy.sh — install dependencies and deploy the WaterWorks Pipeline range.
#
# Run from a shell where the `ludus` client has an API key configured (the Ludus
# host, or any box with the client set up). Safe to re-run; all role adds use -f
# and `ludus range deploy` is idempotent.
#
# The range ID is "waterworks" (override with RANGE=<id>). The script creates the
# range if it does not yet exist, pushes range.yaml, and deploys.
#
# Usage:
#   ./deploy.sh deps        # install local roles only
#   ./deploy.sh config      # create range (if needed) + push range.yaml
#   ./deploy.sh deploy      # deps + config + full deploy        (default)
#   ./deploy.sh roles       # re-run user-defined roles only  (-t user-defined-roles)
#   ./deploy.sh network     # re-apply firewall rules only     (-t network)
#   ./deploy.sh status      # show range status
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

LUDUS="${LUDUS:-ludus}"
RANGE="${RANGE:-waterworks}"          # the --range flag value used everywhere
RANGE_ARGS=(--range "$RANGE")

LOCAL_ROLES=(
  roles/ww_web_portal
  roles/ww_fileserver
  roles/ww_itadmin
  roles/ww_historian
  roles/ww_jumphost
  roles/ww_hmi
  roles/ww_engws
  roles/ww_plc
  roles/ww_scoreboard
  roles/ww_sanitize
)

install_deps() {
  echo "==> Installing local roles from this project"
  for d in "${LOCAL_ROLES[@]}"; do
    if [[ -d "$HERE/$d" ]]; then
      echo "    - $d"
      "$LUDUS" ansible role add -d "$HERE/$d" -f
    else
      echo "    ! missing $d (skipping)"
    fi
  done
  echo "==> Installed roles:"
  "$LUDUS" ansible roles list 2>/dev/null | grep -i '^ww_\| ww_' || true
}

ensure_range() {
  if "$LUDUS" range list "${RANGE_ARGS[@]}" >/dev/null 2>&1; then
    echo "==> Range '$RANGE' already exists"
  else
    echo "==> Creating range '$RANGE'"
    "$LUDUS" range create --name "$RANGE" --range "$RANGE" \
      --description "WaterWorks Pipeline ICS/OT red-team range" \
      --purpose "Training" || {
        echo "    (create failed — if your client lacks 'range create', create the"
        echo "     range in the Ludus UI with ID '$RANGE', then re-run)"; }
  fi
}

push_config() {
  ensure_range
  echo "==> Pushing range configuration"
  "$LUDUS" range config set -f "$HERE/range.yaml" "${RANGE_ARGS[@]}"
}

case "${1:-deploy}" in
  deps)    install_deps ;;
  config)  push_config ;;
  deploy)
    install_deps
    push_config
    echo "==> Deploying range (first run builds 11 VMs; allow 30-60 min)"
    "$LUDUS" range deploy "${RANGE_ARGS[@]}"
    echo "==> Follow progress with: $LUDUS range logs -f ${RANGE_ARGS[*]}"
    ;;
  roles)
    push_config
    "$LUDUS" range deploy -t user-defined-roles "${RANGE_ARGS[@]}"
    ;;
  network)
    push_config
    "$LUDUS" range deploy -t network "${RANGE_ARGS[@]}"
    ;;
  status)  "$LUDUS" range list "${RANGE_ARGS[@]}" ;;
  *) echo "unknown command: $1"; sed -n '13,24p' "$0"; exit 2 ;;
esac

echo "==> Done. Status: $LUDUS range list ${RANGE_ARGS[*]}"
