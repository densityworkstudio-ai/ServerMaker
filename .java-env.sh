#!/usr/bin/env bash
# Sets JAVA_HOME to a Java 21 runtime. Sourced by install.sh and start.sh.
_java_env_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

_java_home_is_21() {
  [[ -n "$1" && -x "$1/bin/java" ]] || return 1
  [[ "$("$1/bin/java" -version 2>&1 | sed -n '1s/.*version "\([0-9]*\).*/\1/p')" == "21" ]]
}

_java_candidates=("$_java_env_root/data/java" "${JAVA_HOME:-}" "/usr/local/sdkman/candidates/java/current")
_system_java="$(command -v java || true)"
if [[ -n "$_system_java" ]]; then
  _java_candidates+=("$(dirname "$(dirname "$(readlink -f "$_system_java")")")")
fi

JAVA_HOME=""
for _candidate in "${_java_candidates[@]}"; do
  if _java_home_is_21 "$_candidate"; then
    JAVA_HOME="$_candidate"
    break
  fi
done

if [[ -n "$JAVA_HOME" ]]; then
  export JAVA_HOME
  export PATH="$JAVA_HOME/bin:$PATH"
fi

unset _java_candidates _candidate _system_java
unset -f _java_home_is_21
