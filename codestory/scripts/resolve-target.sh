#!/usr/bin/env bash
#
# resolve-target.sh — resolve a codestory target to a narratable file set.
#
# Target resolution, exclusion of non-narratable files and size-tier detection
# are deterministic, order-dependent work that must not be improvised per run:
# a wrong exclusion is a silently unnarrated file, which is the failure mode
# codestory is least able to tolerate. Keeping it here also makes the tier
# reproducible across sessions, which resuming a story depends on.
#
# Emits a single JSON object on stdout. Diagnostics go to stderr.

set -euo pipefail

# Associative arrays below need bash 4; macOS ships 3.2 as /bin/bash.
if [ "${BASH_VERSINFO[0]:-0}" -lt 4 ]; then
  printf 'resolve-target: needs bash 4 or newer (found %s). Install a modern bash and re-run.\n' \
    "${BASH_VERSION:-unknown}" >&2
  exit 1
fi

readonly SMALL_MAX_LOC=10000
readonly MEDIUM_MAX_LOC=50000

usage() {
  cat <<'USAGE'
Usage: resolve-target.sh --kind <kind> [options]

Kinds:
  working-tree        Staged, unstaged and untracked changes (shape: change)
  pr                  A pull request; --ref <number>, or omit for the current
                      branch's PR (shape: change; requires gh)
  branch              A branch, diffed against its merge-base with the default
                      branch; --ref <branch> (shape: change)
  path                A file or directory; --ref <path> (shape: state)
  project             The whole repository (shape: state)

Options:
  --kind <kind>       Required. One of the kinds above.
  --ref <ref>         PR number, branch name or path, depending on --kind.
  --base <ref>        Override the base for change-shaped targets.
  --help              Show this message.

Output: one JSON object with target, base_sha, head_sha, default_branch, dirty,
files (path + loc), excluded (path + reason), deleted, formatting_only,
narratable, loc, file_count, tier, warnings. Exits 0 whenever the target
resolved, even when nothing is narratable — check `narratable`. Exits 1 only
when the target could not be resolved at all.
USAGE
}

die() {
  printf 'resolve-target: %s\n' "$1" >&2
  exit 1
}

# --- argument parsing -------------------------------------------------------

kind=""
ref=""
base_override=""

while [ $# -gt 0 ]; do
  case "$1" in
    --kind)
      [ $# -ge 2 ] || die "--kind needs a value"
      kind="$2"
      shift 2
      ;;
    --ref)
      [ $# -ge 2 ] || die "--ref needs a value"
      ref="$2"
      shift 2
      ;;
    --base)
      [ $# -ge 2 ] || die "--base needs a value"
      base_override="$2"
      shift 2
      ;;
    --help | -h)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

[ -n "$kind" ] || {
  usage >&2
  die "--kind is required"
}

case "$kind" in
  working-tree | pr | branch | path | project) ;;
  *) die "unknown kind: $kind" ;;
esac

# --- preflight --------------------------------------------------------------

git rev-parse --is-inside-work-tree >/dev/null 2>&1 ||
  die "not inside a git repository"

# --ref paths are relative to where the user invoked this, not the repo root.
invocation_cwd="$PWD"
repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

warnings=()

default_branch=""
if upstream_head="$(git symbolic-ref --quiet refs/remotes/origin/HEAD 2>/dev/null)"; then
  default_branch="${upstream_head#refs/remotes/origin/}"
fi
if [ -z "$default_branch" ]; then
  for candidate in main master trunk; do
    if git show-ref --verify --quiet "refs/heads/$candidate"; then
      default_branch="$candidate"
      break
    fi
  done
fi
[ -n "$default_branch" ] || default_branch="main"

dirty=false
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  dirty=true
fi

head_sha="$(git rev-parse HEAD 2>/dev/null || echo "")"
[ -n "$head_sha" ] || die "repository has no commits to narrate"

# --- target resolution ------------------------------------------------------

shape="state"
base_sha=""
diff_head=""
candidates=()
deleted=()
formatting=()

resolve_change_files() {
  # $1: base ref, $2: head ref (empty head means "against the working tree").
  # Populates `candidates` with changed paths that still exist, `deleted` with
  # paths the change removes, and `formatting_only` with paths whose diff
  # disappears once whitespace is ignored.
  local base="$1" head="$2" path
  local -a diff_args=("$base")
  [ -z "$head" ] || diff_args+=("$head")
  diff_head="$head"

  while IFS= read -r path; do
    [ -n "$path" ] || continue
    [ -e "$path" ] || continue
    candidates+=("$path")
  done < <(git diff --name-only --diff-filter=d "${diff_args[@]}")

  # Deleted paths have no current content to excerpt, but a reviewer must still
  # be told the change removes them — silence here is the failure this script
  # exists to prevent.
  while IFS= read -r path; do
    [ -n "$path" ] || continue
    deleted+=("$path")
  done < <(git diff --name-only --diff-filter=D "${diff_args[@]}")

  # `git diff -w` is the only cheap whitespace-insensitive test git offers, and
  # it is not safe as an exclusion: a line re-indented into an enclosing block
  # is a control-flow change with a whitespace-only diff, and `"a b"` becoming
  # `"a  b"` is a string change in any language. Both vanish under -w (and -b).
  # So this flags files as *probably* formatting churn, to be summarised in a
  # line rather than given beats — it never removes them from the story.
  # Indentation-significant languages skip the test entirely.
  local -A substantive=()
  while IFS= read -r path; do
    [ -n "$path" ] || continue
    substantive["$path"]=1
  done < <(git diff -w --name-only --diff-filter=d "${diff_args[@]}")

  for path in ${candidates[@]+"${candidates[@]}"}; do
    case "$path" in
      *.py | *.pyi | *.yaml | *.yml | *.nim | *.hs | *.lhs | *.elm | *.coffee | \
        *.haml | *.slim | *.pug | *.jade | *.sass | *.styl | *.md | *.rst | \
        Makefile | *.mk | makefile)
        continue
        ;;
    esac
    [ -n "${substantive["$path"]:-}" ] && continue
    # Whitespace inside a string literal is content, and `-w` hides it. No cheap
    # textual test separates that from churn, so decline to claim "formatting"
    # whenever a changed line carries a quote.
    if git diff -U0 "${diff_args[@]}" -- "$path" 2>/dev/null |
      LC_ALL=C grep -qE "^[+-][^+-].*[\"'\`]"; then
      continue
    fi
    formatting+=("$path")
  done
}

case "$kind" in
  working-tree)
    shape="change"
    base_sha="$head_sha"
    resolve_change_files HEAD ""
    # Untracked files are new in full; they cannot be formatting-only.
    while IFS= read -r path; do
      [ -n "$path" ] || continue
      candidates+=("$path")
    done < <(git ls-files --others --exclude-standard)
    if [ "${#candidates[@]}" -eq 0 ] && [ "${#deleted[@]}" -eq 0 ]; then
      warnings+=("working tree is clean; nothing to narrate")
    fi
    ;;

  pr)
    shape="change"
    command -v gh >/dev/null 2>&1 ||
      die "gh is not installed; use --kind branch to narrate this branch against its merge-base instead"
    pr_selector="${ref:-}"
    if [ -z "$pr_selector" ]; then
      pr_selector="$(git rev-parse --abbrev-ref HEAD)"
      [ "$pr_selector" != "HEAD" ] ||
        die "detached HEAD and no --ref; pass a PR number"
    fi
    pr_tsv="$(gh pr view "$pr_selector" --json number,baseRefName,headRefOid \
      --jq '[.number, .baseRefName, .headRefOid] | @tsv' 2>/dev/null)" ||
      die "could not read PR '$pr_selector' (gh unauthenticated, or no such PR)"
    IFS=$'\t' read -r ref pr_base pr_head_sha <<<"$pr_tsv"
    [ -n "$pr_base" ] || die "could not determine the PR's base branch"
    if [ -n "$pr_head_sha" ] && git cat-file -e "$pr_head_sha^{commit}" 2>/dev/null; then
      head_sha="$pr_head_sha"
    else
      warnings+=("PR head commit is not present locally; narrating from HEAD — run 'git fetch' for the exact PR state")
    fi
    base_ref="${base_override:-origin/$pr_base}"
    git rev-parse --verify --quiet "$base_ref" >/dev/null ||
      base_ref="${base_override:-$pr_base}"
    base_sha="$(git merge-base "$base_ref" "$head_sha" 2>/dev/null)" ||
      die "could not find a merge-base between '$base_ref' and the PR head"
    resolve_change_files "$base_sha" "$head_sha"
    ;;

  branch)
    shape="change"
    branch_ref="${ref:-HEAD}"
    git rev-parse --verify --quiet "$branch_ref" >/dev/null ||
      die "no such branch or ref: $branch_ref"
    head_sha="$(git rev-parse "$branch_ref")"
    base_ref="${base_override:-origin/$default_branch}"
    git rev-parse --verify --quiet "$base_ref" >/dev/null ||
      base_ref="${base_override:-$default_branch}"
    git rev-parse --verify --quiet "$base_ref" >/dev/null ||
      die "could not resolve a base branch (tried '$base_ref')"
    base_sha="$(git merge-base "$base_ref" "$head_sha" 2>/dev/null)" ||
      die "'$branch_ref' and '$base_ref' have no common ancestor"
    if [ "$base_sha" = "$head_sha" ]; then
      warnings+=("'$branch_ref' has no commits beyond '$base_ref'; nothing to narrate")
    fi
    resolve_change_files "$base_sha" "$head_sha"
    ;;

  path)
    [ -n "$ref" ] || die "--kind path needs --ref <file-or-directory>"
    path_arg="$ref"
    case "$path_arg" in
      /*) ;;
      *)
        if [ -e "$invocation_cwd/$path_arg" ]; then
          path_arg="$invocation_cwd/$path_arg"
        fi
        ;;
    esac
    [ -e "$path_arg" ] || die "no such file or directory: $ref"
    # `ref` feeds the story slug, so it must name the same target from any
    # directory — otherwise resume silently forks into a second story file.
    if resolved="$(realpath --relative-to="$repo_root" "$path_arg" 2>/dev/null)"; then
      ref="$resolved"
    fi
    [ "$ref" != "." ] || ref=""
    while IFS= read -r path; do
      [ -n "$path" ] || continue
      candidates+=("$path")
    done < <(git ls-files --cached --others --exclude-standard -- "$path_arg")
    if [ "${#candidates[@]}" -eq 0 ]; then
      warnings+=("'$ref' contains no narratable files (all ignored, or an empty directory)")
    fi
    ;;

  project)
    while IFS= read -r path; do
      [ -n "$path" ] || continue
      candidates+=("$path")
    done < <(git ls-files)
    ;;
esac

if [ "$shape" = "change" ] && [ "$dirty" = true ] && [ "$kind" != "working-tree" ]; then
  warnings+=("working tree is dirty; the story describes ${head_sha:0:12}, which is not what is currently on disk")
fi

# --- exclusions -------------------------------------------------------------

# Returns the exclusion reason on stdout, or nothing if the file is narratable.
exclusion_reason() {
  local path="$1" name="${1##*/}" lower
  lower="$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]')"

  case "/$path/" in
    */.stories/*)
      printf 'codestory-output'
      return
      ;;
  esac

  case "/$path/" in
    */node_modules/* | */vendor/* | */third_party/* | */3rdparty/* | */external/* | \
      */.venv/* | */venv/* | */site-packages/* | */bower_components/* | */.yarn/*)
      printf 'vendored'
      return
      ;;
    */.git/* | */.tox/* | */.mypy_cache/* | */.pytest_cache/* | */__pycache__/*)
      printf 'tooling'
      return
      ;;
  esac

  case "$lower" in
    package-lock.json | npm-shrinkwrap.json | yarn.lock | pnpm-lock.yaml | \
      cargo.lock | poetry.lock | uv.lock | pdm.lock | pipfile.lock | gemfile.lock | \
      composer.lock | go.sum | flake.lock | packages.lock.json | gradle.lockfile | \
      mix.lock | pubspec.lock | podfile.lock | package-lock.yaml)
      printf 'lockfile'
      return
      ;;
  esac

  case "$lower" in
    *.pb.go | *.pb.cc | *.pb.h | *_pb2.py | *_pb2_grpc.py | *_pb.js | *.pb.dart | \
      *.g.dart | *.freezed.dart | *.g.cs | *.designer.cs | *.generated.* | \
      *_generated.* | *.gen.go | *.min.js | *.min.css | *.js.map | *.css.map)
      printf 'generated'
      return
      ;;
  esac

  case "$lower" in
    *.png | *.jpg | *.jpeg | *.gif | *.webp | *.ico | *.svg | *.pdf | *.woff | \
      *.woff2 | *.ttf | *.otf | *.eot | *.mp3 | *.mp4 | *.mov | *.wav | *.zip | \
      *.gz | *.tar | *.bz2 | *.xz | *.7z | *.jar | *.war | *.so | *.dylib | *.dll | \
      *.exe | *.o | *.a | *.class | *.pyc | *.wasm | *.bin | *.dat | *.db | *.sqlite)
      printf 'binary-or-asset'
      return
      ;;
  esac

  if [ -f "$path" ] && ! LC_ALL=C grep -qI . "$path" 2>/dev/null; then
    printf 'binary-or-asset'
    return
  fi

  # Machine-generated files conventionally announce themselves in a header.
  if [ -f "$path" ] &&
    head -n 5 "$path" 2>/dev/null | LC_ALL=C grep -qiE 'DO NOT EDIT|@generated|Code generated by|autogenerated|auto-generated'; then
    printf 'generated'
    return
  fi
}

# --- JSON assembly ----------------------------------------------------------

# `wc -l` counts newlines, so a file with no trailing newline is short by one.
count_lines() {
  local n
  n="$(awk 'END { print NR }' "$1" 2>/dev/null)"
  [ -n "$n" ] || n=0
  printf '%s' "$n"
}

json_escape() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\t'/\\t}"
  s="${s//$'\n'/\\n}"
  s="${s//$'\r'/\\r}"
  printf '%s' "$s"
}

files_json=""
excluded_json=""
total_loc=0
file_count=0
excluded_count=0

for path in ${candidates[@]+"${candidates[@]}"}; do
  reason="$(exclusion_reason "$path")"
  if [ -n "$reason" ]; then
    [ -z "$excluded_json" ] || excluded_json+=","
    excluded_json+="$(printf '{"path":"%s","reason":"%s"}' "$(json_escape "$path")" "$reason")"
    excluded_count=$((excluded_count + 1))
    continue
  fi
  loc=0
  if [ "$shape" = "change" ] && [ -n "$base_sha" ]; then
    # For a change, the narratable size is the churn, not the file's length —
    # a one-line edit to a 40k-line file is a small story, not a large one.
    loc="$(git diff --numstat "$base_sha" ${diff_head:+"$diff_head"} -- "$path" 2>/dev/null |
      awk '{ added += $1; removed += $2 } END { print added + removed + 0 }')"
    [ -n "$loc" ] || loc=0
    # Untracked files have no diff; count them in full.
    if [ "$loc" -eq 0 ] && [ -f "$path" ]; then
      loc="$(count_lines "$path")"
    fi
  elif [ -f "$path" ]; then
    loc="$(count_lines "$path")"
  fi
  [ -z "$files_json" ] || files_json+=","
  files_json+="$(printf '{"path":"%s","loc":%s}' "$(json_escape "$path")" "$loc")"
  total_loc=$((total_loc + loc))
  file_count=$((file_count + 1))
done

formatting_json=""
for path in ${formatting[@]+"${formatting[@]}"}; do
  [ -z "$formatting_json" ] || formatting_json+=","
  formatting_json+="\"$(json_escape "$path")\""
done

deleted_json=""
for path in ${deleted[@]+"${deleted[@]}"}; do
  [ -z "$deleted_json" ] || deleted_json+=","
  deleted_json+="\"$(json_escape "$path")\""
done

narratable=true
if [ "$file_count" -eq 0 ] && [ "${#deleted[@]}" -eq 0 ]; then
  narratable=false
  if [ "${#candidates[@]}" -gt 0 ]; then
    warnings+=("every file in this target was excluded as non-narratable; there is nothing to narrate")
  elif [ "${#warnings[@]}" -eq 0 ]; then
    warnings+=("this target resolved to no files at all; there is nothing to narrate")
  fi
fi

if [ "$total_loc" -lt "$SMALL_MAX_LOC" ]; then
  tier="small"
elif [ "$total_loc" -lt "$MEDIUM_MAX_LOC" ]; then
  tier="medium"
else
  tier="large"
fi

warnings_json=""
for warning in ${warnings[@]+"${warnings[@]}"}; do
  [ -z "$warnings_json" ] || warnings_json+=","
  warnings_json+="\"$(json_escape "$warning")\""
done

printf '{'
printf '"target":{"kind":"%s","ref":"%s","shape":"%s"},' \
  "$(json_escape "$kind")" "$(json_escape "$ref")" "$shape"
printf '"default_branch":"%s",' "$(json_escape "$default_branch")"
printf '"base_sha":"%s","head_sha":"%s","dirty":%s,' \
  "$(json_escape "$base_sha")" "$(json_escape "$head_sha")" "$dirty"
printf '"narratable":%s,"tier":"%s","loc":%s,"file_count":%s,' \
  "$narratable" "$tier" "$total_loc" "$file_count"
printf '"excluded_count":%s,"deleted_count":%s,"formatting_only_count":%s,' \
  "$excluded_count" "${#deleted[@]}" "${#formatting[@]}"
printf '"files":[%s],' "$files_json"
printf '"excluded":[%s],' "$excluded_json"
printf '"deleted":[%s],' "$deleted_json"
printf '"formatting_only":[%s],' "$formatting_json"
printf '"warnings":[%s]' "$warnings_json"
printf '}\n'
