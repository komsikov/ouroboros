#!/bin/sh

set -eu

# Usage:
#   sync_dirs.sh <REPO_DIR> <DATA_DIR> <TARGET_DIR> [INTERVAL_SECONDS]
#
# - Initializes REPO_DIR and DATA_DIR from bundle archive in TARGET_DIR when REPO_DIR is empty.
# - Then continuously updates bundle archive in TARGET_DIR every INTERVAL_SECONDS (default: 5).
# - On SIGINT/SIGTERM performs a final sync and exits.

if [ "$#" -lt 3 ]; then
    echo "Передано недостаточно аргументов, скрипт не будет синхронизировать данные"
    echo "Использование: $0 <REPO_DIR> <DATA_DIR> <TARGET_DIR> [INTERVAL_SECONDS]"
    exit 0
fi

REPO_DIR="$1"
DATA_DIR="$2"
TARGET_DIR="$3"
INTERVAL_SECONDS="${4:-5}"
ARCHIVE_NAME="${OUROBOROS_BUNDLE_ARCHIVE_NAME:-ouroboros-bundle.zip}"
ARCHIVE_PATH="${TARGET_DIR}/${ARCHIVE_NAME}"

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

# Cheap content signature (mtime+size+path) of repo+data. Used to skip a
# rebuild when nothing changed, so an idle agent does not rewrite the archive
# on the S3 mount every cycle.
repo_data_signature() {
    find "$1" "$2" -type f \
        -not -path '*/__pycache__/*' \
        -printf '%T@ %s %p\n' 2>/dev/null | LC_ALL=C sort | md5sum
}

# Build the bundle on LOCAL disk, then publish it to the (possibly S3-FUSE)
# target with a single streaming copy + atomic rename. Never let zip write or
# seek directly on the mount: its random-access writes are unsupported by
# mountpoint-s3 and leak file descriptors on s3fs, which is what brings the
# node down with "too many open files".
create_bundle_archive() {
    repo_dir="$1"
    data_dir="$2"
    tgt="$3"
    archive_path="$4"
    archive_tmp_path="${archive_path}.tmp"
    staging_dir="$(mktemp -d)"
    local_archive="${staging_dir}/bundle.zip"
    mkdir -p "$repo_dir" "$data_dir" "$tgt"
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

    # One sequential write to the mount, then atomic rename on the same
    # filesystem so readers never observe a half-written archive.
    cp -f "$local_archive" "$archive_tmp_path"
    mv -f "$archive_tmp_path" "$archive_path"
    rm -rf "$staging_dir"
}

restore_from_bundle_archive() {
    archive_path="$1"
    repo_dir="$2"
    data_dir="$3"
    staging_dir="$(mktemp -d)"
    if ! unzip -q "$archive_path" -d "$staging_dir"; then
        rm -rf "$staging_dir"
        return 1
    fi

    mkdir -p "$repo_dir" "$data_dir"
    clear_dir_contents "$repo_dir"
    clear_dir_contents "$data_dir"

    if [ -d "$staging_dir/repo" ]; then
        cp -a "$staging_dir/repo"/. "$repo_dir"/
    fi
    if [ -d "$staging_dir/data" ]; then
        cp -a "$staging_dir/data"/. "$data_dir"/
    fi

    rm -rf "$staging_dir"
}

handle_signal() {
    echo "Получен сигнал остановки, выполняем финальную синхронизацию..."
    create_bundle_archive "$REPO_DIR" "$DATA_DIR" "$TARGET_DIR" "$ARCHIVE_PATH"
    echo "Финальная синхронизация завершена"
    exit 0
}

trap handle_signal INT TERM

mkdir -p "$REPO_DIR" "$DATA_DIR" "$TARGET_DIR"

if ! has_entries "$REPO_DIR"; then
    if [ -s "$ARCHIVE_PATH" ]; then
        echo "REPO_DIR=$REPO_DIR пустая — восстанавливаю repo/data из архива $ARCHIVE_PATH ..."
        if restore_from_bundle_archive "$ARCHIVE_PATH" "$REPO_DIR" "$DATA_DIR"; then
            echo "Данные runtime repo/data восстановлены."
        else
            echo "Не удалось восстановить runtime repo/data из архива $ARCHIVE_PATH"
            exit 1
        fi
    elif has_entries "$TARGET_DIR"; then
        echo "REPO_DIR=$REPO_DIR пустая, но архив $ARCHIVE_PATH не найден."
        echo "TARGET_DIR=$TARGET_DIR содержит данные, но они не упакованы в ожидаемый архив."
    else
        echo "Обе директории пусты."
    fi
else
    echo "REPO_DIR=$REPO_DIR содержит данные — используем как источник."
fi

if [ ! -s "$ARCHIVE_PATH" ] && { has_entries "$REPO_DIR" || has_entries "$DATA_DIR"; }; then
    echo "Архив $ARCHIVE_PATH отсутствует или пуст — создаю начальный архив."
    create_bundle_archive "$REPO_DIR" "$DATA_DIR" "$TARGET_DIR" "$ARCHIVE_PATH"
fi

echo "Скрипт завершил инициализацию. Синхронизация запущена: bundle-архив обновляется каждые ${INTERVAL_SECONDS} секунд (REPO_DIR=$REPO_DIR, DATA_DIR=$DATA_DIR, ARCHIVE_PATH=$ARCHIVE_PATH)."

last_signature=""
while true; do
    signature="$(repo_data_signature "$REPO_DIR" "$DATA_DIR")"
    if [ "$signature" != "$last_signature" ]; then
        # The `if` neutralizes `set -e` so a transient mount/S3 error retries on
        # the next cycle instead of killing the sync daemon permanently.
        if create_bundle_archive "$REPO_DIR" "$DATA_DIR" "$TARGET_DIR" "$ARCHIVE_PATH"; then
            last_signature="$signature"
        else
            echo "Не удалось обновить bundle-архив, повтор на следующем цикле." >&2
        fi
    fi
    sleep "$INTERVAL_SECONDS"
done
