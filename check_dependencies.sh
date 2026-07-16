#!/bin/bash
# Install the OS packages listed in dependencies.txt (Debian/apt).
# Sourced by install.sh / update.sh. On systems without apt/dpkg it prints a
# warning and does nothing (so a non-Debian install.sh under `set -e` is not aborted).
if ! command -v dpkg-query >/dev/null 2>&1 || ! command -v apt >/dev/null 2>&1; then
    echo "check_dependencies: apt/dpkg not found — skipping OS dependency install."
    echo "  Install these manually: $(tr '\n' ' ' < dependencies.txt)"
else
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
            sudo apt install -y $pkg_name
        else
            wget -q --show-progress "$deb_url" -O "$tmp_file"
            sudo apt install -y "$tmp_file"
            if [[ -f "$tmp_file" ]]; then
                rm -f "$tmp_file"
            fi
        fi
	fi
done
fi
