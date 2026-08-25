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

Output: one JSON object with target, base_sha, head_sha, source_ref,
content_fingerprint, repo_root, default_branch, dirty, files (path + loc), excluded
(path + reason), deleted, missing, formatting_only, narratable, loc,
file_count, tier, warnings. `loc` is diff churn for a change target — added and
removed lines, deletions included — and file lines for a state target.
`source_ref` is the revision the story describes: read every file at it, since
a non-empty value that differs from HEAD means the checkout holds something
else. `content_fingerprint` is set instead when the source is the working tree
rather than a commit, and is what a resume must compare — no SHA changes when
an uncommitted edit does. `missing` lists tracked paths that are gone from
disk. Every path in the output is relative to `repo_root`, which is not
necessarily where this was invoked — resolve them against it. Exits 0 whenever
the target resolved, even when nothing is narratable —
check `narratable`. Exits 1 only when the target could not be resolved at all.
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
# --kind pr and --kind branch reassign head_sha below; this keeps what is
# actually on disk, so the two can be compared and the difference reported.
checkout_sha="$head_sha"

# --- revision-aware reads ---------------------------------------------------

# A change-shaped target names a revision that need not be the one checked out:
# `--kind branch other`, run from a clean checkout of `main`, must still see the
# files `other` adds. Testing for them on disk finds nothing and drops them
# without a word — the failure this script exists to prevent — and the files
# that do survive get read at the wrong revision. So every existence test and
# every content read goes through the three below. An empty revision means the
# working tree, which is what `working-tree`, `path` and `project` narrate.

path_exists() {
  # $1: revision, or empty for the working tree. $2: repo-relative path.
  # Deliberately as permissive as the `[ -e ]` it replaces: a submodule entry
  # is not narratable, but dropping it here would drop it silently. `-L` covers
  # a broken symlink, which `-e` reports as absent because it follows the link.
  if [ -n "$1" ]; then
    git cat-file -e "$1:$2" 2>/dev/null
  else
    [ -e "$2" ] || [ -L "$2" ]
  fi
}

has_content() {
  # The revision-aware form of `[ -f ]`: true only where there are file bytes to
  # sniff or count, so directories and submodule entries skip those checks. A
  # symlink has content — its link value — and `-L` is tested first so that
  # answer does not depend on whether the link currently resolves.
  if [ -n "$1" ]; then
    [ "$(git cat-file -t "$1:$2" 2>/dev/null)" = blob ]
  else
    [ -L "$2" ] || [ -f "$2" ]
  fi
}

read_blob() {
  # Callers must consume this to completion. Under `set -o pipefail` a reader
  # that exits early (`grep -q`, `head`) sends git SIGPIPE, and the pipeline
  # then reports failure even though the reader succeeded.
  # A symlink's content is its link value, which is what git stores and what
  # the ref branch below returns. Following it instead would pull an outside
  # file's bytes into the story under a repository path, and count and classify
  # the story's subject by content the repository does not contain.
  if [ -n "$1" ]; then
    git cat-file blob "$1:$2" 2>/dev/null
  elif [ -L "$2" ]; then
    readlink -- "$2" 2>/dev/null
  else
    cat -- "$2" 2>/dev/null
  fi
}

# --- target resolution ------------------------------------------------------

shape="state"
base_sha=""
diff_head=""
candidates=()
deleted=()
formatting=()
missing=()
# Only a genuinely untracked path may fall back to counting its whole length;
# see the loc fallback far below for why `loc == 0` alone is not the same test.
declare -A untracked_set=()

resolve_change_files() {
  # $1: base ref, $2: head ref (empty head means "against the working tree").
  # Populates `candidates` with changed paths that still exist, `deleted` with
  # paths the change removes, and `formatting_only` with paths whose diff
  # disappears once whitespace is ignored.
  local base="$1" head="$2" path
  local -a diff_args=("$base")
  [ -z "$head" ] || diff_args+=("$head")
  diff_head="$head"

  # -z on every enumeration below. Git C-quotes any path holding a non-ASCII
  # byte, a newline, a tab or a quote — `café.txt` comes back as the literal
  # `"caf\303\251.txt"`, which names no file on disk — and NUL is the only
  # delimiter a pathname cannot itself contain.
  while IFS= read -r -d '' path; do
    [ -n "$path" ] || continue
    path_exists "$head" "$path" || continue
    candidates+=("$path")
  done < <(git diff -z --name-only --diff-filter=d "${diff_args[@]}")

  # Deleted paths have no current content to excerpt, but a reviewer must still
  # be told the change removes them — silence here is the failure this script
  # exists to prevent.
  while IFS= read -r -d '' path; do
    [ -n "$path" ] || continue
    deleted+=("$path")
  done < <(git diff -z --name-only --diff-filter=D "${diff_args[@]}")

  # `git diff -w` is the only cheap whitespace-insensitive test git offers, and
  # it is not safe as an exclusion: a line re-indented into an enclosing block
  # is a control-flow change with a whitespace-only diff, and `"a b"` becoming
  # `"a  b"` is a string change in any language. Both vanish under -w (and -b).
  # So this flags files as *probably* formatting churn, to be summarised in a
  # line rather than given beats — it never removes them from the story.
  # Indentation-significant languages skip the test entirely.
  local -A substantive=()
  # Keyed by the same spelling the candidates loop looks up, so this
  # enumeration has to be NUL-delimited in the same breath as that one:
  # convert only one and every non-ASCII path misses its key here and is
  # wrongly called formatting-only.
  while IFS= read -r -d '' path; do
    [ -n "$path" ] || continue
    substantive["$path"]=1
  done < <(git diff -z -w --name-only --diff-filter=d "${diff_args[@]}")

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
    # Not `grep -q`: it exits on the first match, and the SIGPIPE that sends
    # git makes the pipeline fail under `set -o pipefail` — so a diff larger
    # than the pipe buffer takes the *false* branch precisely when a quote was
    # found, inverting this guard. Consuming the diff keeps git's status 0.
    if git diff -U0 "${diff_args[@]}" -- "$path" 2>/dev/null |
      LC_ALL=C grep -E "^[+-][^+-].*[\"'\`]" >/dev/null; then
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
    while IFS= read -r -d '' path; do
      [ -n "$path" ] || continue
      candidates+=("$path")
      untracked_set["$path"]=1
    done < <(git ls-files -z --others --exclude-standard)
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
    while IFS= read -r -d '' path; do
      [ -n "$path" ] || continue
      if path_exists "" "$path"; then
        candidates+=("$path")
      else
        missing+=("$path")
      fi
    done < <(git ls-files -z --cached --others --exclude-standard -- "$path_arg")
    if [ "${#candidates[@]}" -eq 0 ]; then
      warnings+=("'$ref' contains no narratable files (all ignored, or an empty directory)")
    fi
    ;;

  project)
    # `git ls-files` alone is the index, which is not the project: it omits
    # every untracked source file and keeps files already deleted from disk,
    # so the story would miss new code and send agents to read absent paths.
    while IFS= read -r -d '' path; do
      [ -n "$path" ] || continue
      if path_exists "" "$path"; then
        candidates+=("$path")
      else
        missing+=("$path")
      fi
    done < <(git ls-files -z --cached --others --exclude-standard)
    ;;
esac

if [ "$shape" = "change" ] && [ "$dirty" = true ] && [ "$kind" != "working-tree" ]; then
  warnings+=("working tree is dirty; the story describes ${head_sha:0:12}, which is not what is currently on disk")
fi

# Tracked but gone from disk. Not a deletion the target makes — a state-shaped
# target has no diff — but dropping them without a word is the one thing this
# script may not do.
if [ "${#missing[@]}" -gt 0 ]; then
  warnings+=("${#missing[@]} tracked file(s) are missing from the working tree and cannot be narrated: ${missing[*]}")
fi

# This resolver reads blobs, but the lens agents and the narrator read files —
# and an ordinary read returns the checkout, which for another branch is the
# wrong revision, or for a file that branch adds is nothing at all.
if [ -n "$diff_head" ] && [ "$diff_head" != "$checkout_sha" ]; then
  warnings+=("narrating ${diff_head:0:12}, which is not what is checked out; read every file as 'git show ${diff_head:0:12}:<path>' — a plain read shows the checkout instead")
fi

# --- exclusions -------------------------------------------------------------

# Returns the exclusion reason on stdout, or nothing if the file is narratable.
exclusion_reason() {
  # $1: revision to read content at, or empty for the working tree. $2: path.
  local ref="$1" path="$2" name="${2##*/}" lower
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

  # Both sniffs below read the revision being narrated, and both let their
  # reader drain the stream: `grep -q` and `head` stop early, and the SIGPIPE
  # that sends git fails the pipeline under `set -o pipefail` even on a match.
  # `sed -n '1,5p'` prints five lines but keeps reading to the end.
  if has_content "$ref" "$path" &&
    ! read_blob "$ref" "$path" | LC_ALL=C grep -I . >/dev/null; then
    printf 'binary-or-asset'
    return
  fi

  # Machine-generated files conventionally announce themselves in a header.
  if has_content "$ref" "$path" &&
    read_blob "$ref" "$path" | sed -n '1,5p' |
    LC_ALL=C grep -iE 'DO NOT EDIT|@generated|Code generated by|autogenerated|auto-generated' >/dev/null; then
    printf 'generated'
    return
  fi
}

# --- JSON assembly ----------------------------------------------------------

# `wc -l` counts newlines, so a file with no trailing newline is short by one.
# $1: revision, or empty for the working tree. $2: path. awk drains its input,
# so git is never SIGPIPEd here; a read that fails outright falls back to 0.
count_lines() {
  local n
  n="$(read_blob "$1" "$2" | awk 'END { print NR }')" || n=0
  [ -n "$n" ] || n=0
  printf '%s' "$n"
}

json_escape() {
  # JSON forbids every unescaped byte below 0x20, not just the three with short
  # names. A form feed in a pathname is legal in git and made the whole
  # document unparseable, which for a script whose only output is one JSON
  # object is a total failure. The three below keep their readable spelling;
  # anything else left in the C0 range becomes \u00XX.
  local s="$1" ch hex
  local LC_ALL=C
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\t'/\\t}"
  s="${s//$'\n'/\\n}"
  s="${s//$'\r'/\\r}"
  # One pass per *distinct* control byte present, not per character: each
  # substitution replaces every occurrence, and \u00XX contains none itself,
  # so the loop always terminates.
  while [[ "$s" =~ [[:cntrl:]] ]]; do
    ch="${BASH_REMATCH[0]}"
    printf -v hex '%02X' "'$ch"
    s="${s//"$ch"/\\u00$hex}"
  done
  printf '%s' "$s"
}

files_json=""
excluded_json=""
total_loc=0
file_count=0
excluded_count=0
# Kept alongside the JSON so the fingerprint below can hash the resolved
# inventory without re-deriving any of it.
kept_paths=()
excluded_paths=()
excluded_reasons=()

for path in ${candidates[@]+"${candidates[@]}"}; do
  reason="$(exclusion_reason "$diff_head" "$path")"
  if [ -n "$reason" ]; then
    [ -z "$excluded_json" ] || excluded_json+=","
    excluded_json+="$(printf '{"path":"%s","reason":"%s"}' "$(json_escape "$path")" "$reason")"
    excluded_paths+=("$path")
    excluded_reasons+=("$reason")
    excluded_count=$((excluded_count + 1))
    continue
  fi
  loc=0
  if [ "$shape" = "change" ] && [ -n "$base_sha" ]; then
    # For a change, the narratable size is the churn, not the file's length —
    # a one-line edit to a 40k-line file is a small story, not a large one.
    loc="$(git diff --numstat "$base_sha" ${diff_head:+"$diff_head"} -- "$path" 2>/dev/null |
      awk '{ added += $1; removed += $2 } END { print added + removed + 0 }')" || loc=0
    [ -n "$loc" ] || loc=0
    # Untracked files have no diff; count them in full. Gated on the untracked
    # set rather than on `loc == 0`, because zero churn is also the honest
    # answer for a mode-only change or a pure rename — and counting one of
    # those in full reported `chmod +x` on a 20k-line file as 20k lines of
    # story. For pr and branch targets the set is empty and this never fires.
    if [ "$loc" -eq 0 ] && [ -n "${untracked_set["$path"]:-}" ] &&
      has_content "$diff_head" "$path"; then
      loc="$(count_lines "$diff_head" "$path")"
    fi
  elif has_content "$diff_head" "$path"; then
    loc="$(count_lines "$diff_head" "$path")"
  fi
  [ -z "$files_json" ] || files_json+=","
  files_json+="$(printf '{"path":"%s","loc":%s}' "$(json_escape "$path")" "$loc")"
  kept_paths+=("$path")
  total_loc=$((total_loc + loc))
  file_count=$((file_count + 1))
done

formatting_json=""
for path in ${formatting[@]+"${formatting[@]}"}; do
  [ -z "$formatting_json" ] || formatting_json+=","
  formatting_json+="\"$(json_escape "$path")\""
done

# A deletion never reaches the loop above — it has no surviving content — but
# its removed lines are review cost all the same, and leaving them out of the
# total reported a 12k-line removal as `loc: 0, tier: small`. Deletions are not
# exclusions, so every one of them counts, lockfiles and generated files too.
deleted_json=""
for path in ${deleted[@]+"${deleted[@]}"}; do
  [ -z "$deleted_json" ] || deleted_json+=","
  deleted_json+="\"$(json_escape "$path")\""
  deleted_loc="$(git diff --numstat "$base_sha" ${diff_head:+"$diff_head"} -- "$path" 2>/dev/null |
    awk '{ removed += $2 } END { print removed + 0 }')" || deleted_loc=0
  [ -n "$deleted_loc" ] || deleted_loc=0
  total_loc=$((total_loc + deleted_loc))
done

missing_json=""
for path in ${missing[@]+"${missing[@]}"}; do
  [ -z "$missing_json" ] || missing_json+=","
  missing_json+="\"$(json_escape "$path")\""
done

# --- content fingerprint ----------------------------------------------------

# A target resolved from a commit is identified by its SHA, but working-tree,
# path and project stories are told against content no commit names: edit a
# file and head_sha is still the same, so a resume compares equal and appends
# fresh beats onto beats describing content that has since moved. This hashes
# what was actually resolved — the classification of every path, and the
# current bytes of every kept one — giving resume something that does change.
# NUL framing for the same reason the enumerations use it: a pathname can
# contain anything but NUL. Errs toward reporting a change, never away from it.
content_fingerprint() {
  local path i
  local -a regular=() links=() batch=()
  for path in ${kept_paths[@]+"${kept_paths[@]}"}; do
    if [ -L "$path" ]; then links+=("$path"); else regular+=("$path"); fi
  done
  {
    printf 'kind\0%s\0ref\0%s\0' "$kind" "$ref"
    for i in ${excluded_paths[@]+"${!excluded_paths[@]}"}; do
      # Exclusion records are in the hash so that a change in *coverage* is
      # detected — but not the skill's own output. `.stories/` fills up as the
      # story is written, so hashing those records made narrating a target
      # change its own fingerprint, and the first resume always reported the
      # code as moved. The paths stay in `excluded` either way; only the hash
      # ignores them.
      [ "${excluded_reasons[$i]}" != codestory-output ] || continue
      printf 'x\0%s\0%s\0' "${excluded_paths[$i]}" "${excluded_reasons[$i]}"
    done
    for path in ${missing[@]+"${missing[@]}"}; do printf 'm\0%s\0' "$path"; done
    for path in ${deleted[@]+"${deleted[@]}"}; do printf 'd\0%s\0' "$path"; done
    # A symlink is hashed by its link value, never by what it points at.
    for path in ${links[@]+"${links[@]}"}; do
      printf 'l\0%s\0%s\0' "$path" "$(readlink -- "$path" 2>/dev/null)"
    done
    for path in ${regular[@]+"${regular[@]}"}; do printf 'f\0%s\0' "$path"; done
    # Blob hashes for those regular files, in the order just listed. Batched so
    # a whole-project target costs a handful of git processes, not one per file.
    for path in ${regular[@]+"${regular[@]}"}; do
      batch+=("$path")
      if [ "${#batch[@]}" -ge 200 ]; then
        git hash-object -- "${batch[@]}" 2>/dev/null || printf 'unreadable\n'
        batch=()
      fi
    done
    if [ "${#batch[@]}" -gt 0 ]; then
      git hash-object -- "${batch[@]}" 2>/dev/null || printf 'unreadable\n'
    fi
  } | git hash-object --stdin
}

# Only for targets whose source is not a commit; a change-shaped target
# resolved from a revision is already identified by base_sha and head_sha.
content_hash=""
if [ -z "$diff_head" ]; then
  content_hash="$(content_fingerprint)" || content_hash=""
fi

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
printf '"repo_root":"%s",' "$(json_escape "$repo_root")"
printf '"base_sha":"%s","head_sha":"%s","source_ref":"%s","dirty":%s,' \
  "$(json_escape "$base_sha")" "$(json_escape "$head_sha")" \
  "$(json_escape "$diff_head")" "$dirty"
printf '"content_fingerprint":"%s",' "$(json_escape "$content_hash")"
printf '"narratable":%s,"tier":"%s","loc":%s,"file_count":%s,' \
  "$narratable" "$tier" "$total_loc" "$file_count"
printf '"excluded_count":%s,"deleted_count":%s,"formatting_only_count":%s,' \
  "$excluded_count" "${#deleted[@]}" "${#formatting[@]}"
printf '"missing_count":%s,' "${#missing[@]}"
printf '"files":[%s],' "$files_json"
printf '"excluded":[%s],' "$excluded_json"
printf '"deleted":[%s],' "$deleted_json"
printf '"missing":[%s],' "$missing_json"
printf '"formatting_only":[%s],' "$formatting_json"
printf '"warnings":[%s]' "$warnings_json"
printf '}\n'
