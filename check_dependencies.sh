#!/bin/bash
# Install the OS packages listed in dependencies.txt (Debian/apt).
# Sourced by install.sh / update.sh. On systems without apt/dpkg it prints a
# warning and does nothing (so a non-Debian install.sh under `set -e` is not aborted).
if ! command -v dpkg-query >/dev/null 2>&1 || ! command -v apt >/dev/null 2>&1; then
    echo "check_dependencies: apt/dpkg not found — skipping OS dependency install."
    echo "  Install these manually: $(tr '\n' ' ' < dependencies.txt)"
else
# Use sudo only when we are not already root (root has no sudo in minimal images /
# containers, and would not need it anyway). Fall back to running the command directly.
if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
elif command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
else
    echo "check_dependencies: not root and sudo not found — cannot install OS packages."
    echo "  Install these manually: $(tr '\n' ' ' < dependencies.txt)"
    SUDO="__no_priv__"
fi
if [ "$SUDO" != "__no_priv__" ]; then
for i in $(cat dependencies.txt)
do
    if [[ $i =~ ";" ]]; then
        arrSplit=(${i//;/ })
        pkg_name=${arrSplit[0]}
        deb_url=${arrSplit[1]}
        deb_file=${deb_url##*/}
        tmp_file="/tmp/$deb_file"
    else
        pkg_name=$(echo $i | tr -d '\r')
        deb_url=""
    fi

    if [[ $(dpkg-query -W -f='${Status}' "$pkg_name" 2>/dev/null | grep -c "ok installed") -ne 1 ]]; then
	    echo -e "${pkg_name} is not installed. Installing..."
        if [[ "$deb_url" = "" ]]; then
            $SUDO apt install -y $pkg_name
        else
            wget -q --show-progress "$deb_url" -O "$tmp_file"
            $SUDO apt install -y "$tmp_file"
            if [[ -f "$tmp_file" ]]; then
                rm -f "$tmp_file"
            fi
        fi
	fi
done
fi
fi
