#!/bin/bash

CLEAR_ALL=NO

help_usage() {
    echo "usage: uninstall [[-a | --all] | [-h | --help]]"
}

while [[ $# -gt 0 ]]; do
  key="$1"
  case $key in
    -a | --all )
      CLEAR_ALL=YES
      ;;
    -h | --help )
      help_usage
      exit
      ;;
    * )
      echo "Error: Unknow parameter (${key})!!"
      help_usage
      exit 1
    esac
    shift
done

if [ "$(id -u)" != "0" ]; then
    echo "Sorry, you are not root."
    exit 1
fi

systemctl disable ServiSesentry.timer
systemctl stop ServiSesentry.timer
rm '/lib/systemd/system/ServiSesentry.service'
rm '/lib/systemd/system/ServiSesentry.timer'
systemctl daemon-reload
rm -rf '/opt/ServiSesentry'
rm -rf '/var/lib/ServiSesentry'

if [[ "${CLEAR_ALL}" == "YES" ]]; then
  rm -rf '/etc/ServiSesentry'
fi
