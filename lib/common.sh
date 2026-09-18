#!/usr/bin/env bash
set -eo pipefail
fail() { printf 't4-connection: %s\n' "$*" >&2; exit 1; }
config=${T4_CONFIG:-$HOME/.config/t4-connection/config}
if [[ -f $config ]]; then source "$config"; fi
T4_LOGIN=${T4_LOGIN:-tsubame4}
[[ $T4_LOGIN =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.@-]*$ ]] || fail 'Invalid T4_LOGIN.'
T4_CODE_PORT=${T4_CODE_PORT:-8890}
T4_SSH_PORT=${T4_SSH_PORT:-12345}
T4_LOCAL_PORT=${T4_LOCAL_PORT:-8890}
state_dir=$HOME/.local/state/t4-connection
port() {
    [[ $1 =~ ^[0-9]{4,5}$ ]] || fail 'Port must be 1024-65535.'
    (( 10#$1 >= 1024 && 10#$1 <= 65535 )) || fail 'Port must be 1024-65535.'
}
compute_node() {
    node=$(hostname -s)
    [[ $node =~ ^r[0-9]+n[0-9]+$ && -n ${JOB_ID:-} ]] || fail 'Run inside an allocated compute-node job.'
    umask 077
    mkdir -p "$state_dir"
    chmod 700 "$state_dir"
}
# State is data, never sourced as shell code. One active instance per service.
read_state() {
    local data extra service=$1
    shift
    data=$(ssh "$@" "$T4_LOGIN" "cat .local/state/t4-connection/$service") || fail "No $service state; start the service first."
    [[ $data != *$'\n'* ]] || fail 'Invalid multiline state.'
    read -r node remote_port remote_user extra <<< "$data"
    [[ $node =~ ^r[0-9]+n[0-9]+$ && $remote_user =~ ^[a-zA-Z0-9_][a-zA-Z0-9_-]*$ && -z $extra ]] || fail 'Invalid service state.'
    port "$remote_port"
}
isolated=(-S none -o ControlMaster=no -o ControlPersist=no -o ExitOnForwardFailure=yes)
# Accept only the scheduler's table format, never error text as an empty queue.
scheduler_job_ids() {
    local listing
    listing=$(LC_ALL=C "$1" -u "$(id -un)" 2>&1) || return 1
    printf '%s\n' "$listing" | awk '
        NF == 0 { next }
        $1 == "job-ID" { header=1; next }
        /^[-[:space:]]+$/ { next }
        header && $1 ~ /^[0-9]+$/ && NF >= 5 { print $1; next }
        { bad=1 }
        END { if (bad) exit 1 }
    '
}
# Recovery is serialized inside the old lock; staging is removed after recovery.
acquire_service_lock() (
    if mkdir "$lock" 2>/dev/null; then exit 0; fi
    # Subshell variables survive until EXIT traps, including on Bash 3.2.
    recovery=$lock/recovery
    mkdir "$recovery" 2>/dev/null || fail "Service locked: $lock (recovery busy or inaccessible)."
    trap 'rmdir "$recovery" 2>/dev/null || :' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    trap 'exit 129' HUP
    owner=$(cat "$lock/owner") || fail "Cannot read lock owner: $lock. See README recovery instructions."
    [[ $owner != *$'\n'* ]] || fail "Invalid lock owner: $lock."
    read -r old_node old_job old_pid extra <<< "$owner"
    [[ $old_node =~ ^r[0-9]+n[0-9]+$ && $old_job =~ ^[0-9]+$ && $old_pid =~ ^[0-9]+$ && -z $extra ]] || fail "Invalid lock owner: $lock."
    [[ $old_job != "$JOB_ID" ]] || fail "Service locked: $lock (current job $old_job)."
    iq_jobs=$(scheduler_job_ids iqstat) || fail 'iqstat failed or returned unexpected output; retaining lock.'
    sleep 1
    jobs=$(scheduler_job_ids qstat) || fail 'qstat failed or returned unexpected output; retaining lock.'
    jobs=$(printf '%s\n%s\n' "$iq_jobs" "$jobs")
    if printf '%s\n' "$jobs" | grep -Fxq "$old_job"; then
        fail "Service locked: $lock (job $old_job still exists on scheduler)."
    fi
    printf '%s\n' "$jobs" | grep -Fxq "$JOB_ID" || fail "Current job $JOB_ID is not visible on scheduler; retaining lock."
    [[ $(cat "$lock/owner") == "$owner" ]] || fail 'Lock owner changed during recovery; retaining lock.'
    archive=$(mktemp -d "$state_dir/$service.stale.XXXXXXXX")
    # Move the endpoint before making the lock path available to a new starter.
    if [[ -e $state_dir/$service ]]; then mv "$state_dir/$service" "$archive/endpoint"; fi
    mv "$lock" "$archive/lock"
    recovery=$archive/lock/recovery
    rm -f "$archive/endpoint" "$archive/lock/owner" "$archive/lock/endpoint"
    rmdir "$recovery" "$archive/lock" "$archive"
    printf 'Removed stale %s lock for finished job %s.\n' "$service" "$old_job" >&2
    mkdir "$lock" 2>/dev/null || fail "Service locked: $lock (another starter acquired it)."
)
# Lock each service across nodes; retain a stale lock after an uncatchable kill.
# Never replace another running service's endpoint.
serve() {
    local service=$1 service_port=$2
    shift 2
    port "$service_port"
    service_port=$((10#$service_port))
    local attempts=${T4_PORT_ATTEMPTS:-20} startup_timeout=${T4_STARTUP_TIMEOUT:-30}
    [[ $attempts =~ ^[1-9][0-9]{0,2}$ ]] && (( attempts <= 100 )) || fail 'T4_PORT_ATTEMPTS must be 1-100.'
    [[ $startup_timeout =~ ^[1-9][0-9]{0,2}$ ]] && (( startup_timeout <= 300 )) || fail 'T4_STARTUP_TIMEOUT must be 1-300 seconds.'
    local attempt tick ready result log_file=$state_dir/$service.log marker collision
    local command_args=()
    lock=$state_dir/$service.lock
    acquire_service_lock
    endpoint=$state_dir/$service
    child=
    log_tail=
    cleanup() {
        trap - EXIT INT TERM HUP
        if [[ -n $log_tail ]]; then kill "$log_tail" 2>/dev/null || :; wait "$log_tail" 2>/dev/null || :; fi
        if [[ -n $child ]]; then kill "$child" 2>/dev/null || :; wait "$child" 2>/dev/null || :; fi
        rm -f "$endpoint" "$lock/owner" "$lock/endpoint"
        rmdir "$lock"
    }
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    trap 'exit 129' HUP
    printf '%s %s %s\n' "$node" "${JOB_ID}" "$$" > "$lock/owner"
    # Let the server bind: probing and releasing a port first has a race.
    # Publish only after this process reports listening on the selected port.
    for (( attempt=1; attempt<=attempts && service_port<=65535; attempt++, service_port++ )); do
        case $service in
            code-server)
                command_args=("$@" --bind-addr "0.0.0.0:$service_port")
                collision="EADDRINUSE.*0[.]0[.]0[.]0:$service_port([^0-9]|$)"
                marker="server listening on http(s)?://0\.0\.0\.0:$service_port/"
                ;;
            sshd)
                command_args=("$@" -p "$service_port")
                collision="Bind to port $service_port on 0[.]0[.]0[.]0 failed: Address already in use"
                marker="Server listening on 0\.0\.0\.0 port $service_port\."
                ;;
            *) fail "Unknown service: $service" ;;
        esac
        LC_ALL=C "${command_args[@]}" > "$log_file" 2>&1 &
        child=$!
        ready=false
        for (( tick=0; tick<startup_timeout*10; tick++ )); do
            if ! kill -0 "$child" 2>/dev/null; then break; fi
            if grep -Eq "$marker" "$log_file"; then ready=true; break; fi
            sleep 0.1
        done
        if "$ready" && kill -0 "$child" 2>/dev/null; then break; fi
        if kill -0 "$child" 2>/dev/null; then
            cat "$log_file" >&2
            fail "No listening confirmation within $startup_timeout seconds; see $log_file."
        fi
        result=0
        wait "$child" || result=$?
        child=
        cat "$log_file" >&2
        if (( result != 0 )) && grep -Eq "$collision" "$log_file"; then
            printf '%s port %s is in use; trying the next port.\n' "$service" "$service_port" >&2
        else
            (( result != 0 )) || result=1
            cleanup
            return "$result"
        fi
    done
    [[ -n $child ]] || fail "No available port within $attempts attempts (maximum port 65535)."
    tail -n +1 -f "$log_file" >&2 &
    log_tail=$!
    printf '%s %s %s\n' "$node" "$service_port" "$(id -un)" > "$lock/endpoint"
    mv "$lock/endpoint" "$state_dir/$service"
    printf '%s running on %s:%s (job %s). Stop with Ctrl-C.\n' "$service" "$node" "$service_port" "$JOB_ID" >&2
    printf 'T4_READY %s %s %s %s\n' "$service" "$node" "$service_port" "$JOB_ID"
    result=0
    wait "$child" || result=$?
    cleanup
    return "$result"
}
