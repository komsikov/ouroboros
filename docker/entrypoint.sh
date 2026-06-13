#!/bin/sh

set -eu

REPO_A="${OUROBOROS_REPO_DIR:-/opt/ouroboros}"
REPO_B="/mnt"
IMAGE_REPO="/opt/ouroboros_image"
DATA_DIR="${OUROBOROS_DATA_DIR:-/opt/ouroboros/data}"
BUNDLE_ARCHIVE_NAME="${OUROBOROS_BUNDLE_ARCHIVE_NAME:-ouroboros-bundle.zip}"
BUNDLE_ARCHIVE_PATH="${REPO_B}/${BUNDLE_ARCHIVE_NAME}"
SYNC_INTERVAL_SECONDS="${OUROBOROS_SYNC_INTERVAL_SECONDS:-30}"

has_entries() {
    dir="$1"
    [ -d "$dir" ] || return 1
    for f in "$dir"/*; do
        [ -e "$f" ] && return 0
    done
    return 1
}

clear_dir_contents() {
    dir="$1"
    mkdir -p "$dir"
    rm -rf "$dir"/* "$dir"/.[!.]* "$dir"/..?* 2>/dev/null || true
}

# Build the bundle on LOCAL disk, then publish to the mount with a single
# streaming copy + atomic rename. See ouroboros-sync-dirs for why zip must
# never write directly on the S3 FUSE mount.
create_bundle_archive() {
    repo_dir="$1"
    data_dir="$2"
    archive_path="$3"
    archive_tmp_path="${archive_path}.tmp"
    staging_dir="$(mktemp -d)"
    local_archive="${staging_dir}/bundle.zip"
    mkdir -p "$repo_dir" "$data_dir" "$REPO_B"
    mkdir -p "$staging_dir/payload/repo" "$staging_dir/payload/data"

    if has_entries "$repo_dir"; then
        cp -a "$repo_dir"/. "$staging_dir/payload/repo"/
    fi
    if has_entries "$data_dir"; then
        cp -a "$data_dir"/. "$staging_dir/payload/data"/
    fi

    (
        cd "$staging_dir/payload"
        zip -qr "$local_archive" . \
            -x '*/__pycache__/*' '*.pyc'
    )

    cp -f "$local_archive" "$archive_tmp_path"
    mv -f "$archive_tmp_path" "$archive_path"
    rm -rf "$staging_dir"
}

restore_runtime_from_bundle() {
    [ -s "$BUNDLE_ARCHIVE_PATH" ] || return 1
    staging_dir="$(mktemp -d)"
    if ! unzip -q "$BUNDLE_ARCHIVE_PATH" -d "$staging_dir"; then
        rm -rf "$staging_dir"
        return 1
    fi

    clear_dir_contents "$REPO_A"
    clear_dir_contents "$DATA_DIR"

    if [ -d "$staging_dir/repo" ]; then
        cp -a "$staging_dir/repo"/. "$REPO_A"/
    fi
    if [ -d "$staging_dir/data" ]; then
        cp -a "$staging_dir/data"/. "$DATA_DIR"/
    fi

    rm -rf "$staging_dir"
}

echo "Repo A (OUROBOROS_REPO_DIR) = $REPO_A"
echo "Repo B (mount)             = $REPO_B"
echo "Repo IMAGE               = $IMAGE_REPO"
echo "Data (OUROBOROS_DATA_DIR) = $DATA_DIR"
echo "Bundle archive            = $BUNDLE_ARCHIVE_PATH"

mkdir -p "$REPO_A" "$REPO_B" "$DATA_DIR"

if ! has_entries "$REPO_A"; then
    if [ -s "$BUNDLE_ARCHIVE_PATH" ]; then
        echo "Repo A is empty — restoring runtime repo/data from $BUNDLE_ARCHIVE_PATH..."
        restore_runtime_from_bundle
    elif has_entries "$REPO_B"; then
        echo "Repo B has files, but bundle archive $BUNDLE_ARCHIVE_PATH is missing. Initializing from image."
        cp -a "$IMAGE_REPO"/. "$REPO_A"/
    else
        echo "Repo A and Repo B are empty — initializing Repo A from image..."
        cp -a "$IMAGE_REPO"/. "$REPO_A"/
    fi
elif [ ! -f "$REPO_A/server.py" ]; then
    echo "Repo A has entries but no server.py — seeding application code from image..."
    cp -a "$IMAGE_REPO"/. "$REPO_A"/
else
    echo "Repo A is not empty — using it as the runtime repo."
fi

if [ -d "$REPO_A/.git" ]; then
    remotes="$(git -C "$REPO_A" remote || true)"
    if [ -n "$remotes" ]; then
        echo "Removing git remotes from runtime repo ($REPO_A)..."
        for remote in $remotes; do
            git -C "$REPO_A" remote remove "$remote" || true
        done
    fi
fi

OUROBOROS_BUNDLE_ARCHIVE_NAME="$BUNDLE_ARCHIVE_NAME" /usr/local/bin/ouroboros-sync-dirs "$REPO_A" "$DATA_DIR" "$REPO_B" "$SYNC_INTERVAL_SECONDS" &
SYNC_PID="$!"

SERVER_PID=""

handle_term() {
    echo "EntryPoint got stop signal, terminating children..."

    if [ -n "${SERVER_PID:-}" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
        kill -TERM "$SERVER_PID" 2>/dev/null || true
    fi

    if [ -n "${SYNC_PID:-}" ] && kill -0 "$SYNC_PID" 2>/dev/null; then
        kill -TERM "$SYNC_PID" 2>/dev/null || true
    fi

    # Give the sync process a moment to do final sync, then do a last safety sync ourselves.
    sleep 1 || true
    echo "EntryPoint final safety bundle update (repo+data -> mount)..."
    create_bundle_archive "$REPO_A" "$DATA_DIR" "$BUNDLE_ARCHIVE_PATH" || true
}

trap handle_term INT TERM

cd "$REPO_A"

# Run server from Repo A; forward any args passed to the container
python -m server "$@" &
SERVER_PID="$!"

wait "$SERVER_PID"
EXIT_CODE="$?"

# If server exits normally, still do a final sync to B.
echo "Server exited with code ${EXIT_CODE}. Final bundle update (repo+data -> mount)..."
create_bundle_archive "$REPO_A" "$DATA_DIR" "$BUNDLE_ARCHIVE_PATH" || true

exit "$EXIT_CODE"
