# Service Sentry

> Service Sentry is an effective network monitoring system that ensures the performance and availability of equipment and services through instant alerts and rapid diagnostics. 


## Requirements
* `python3-requests`
* `python3-pymysql`
* `python3-paramiko >= 2.5 (version 2.4 da errores CryptographyDeprecationWarning)`

## Install:
```
$ cd /usr/src
$ git clone https://github.com/vsc55/ServiceSentry.git
$ cd ServiceSentry
$ chmod +x *.sh
$ sudo ./install.sh
```

## Update:
```
$ cd /usr/src/ServiceSentry
$ git pull
$ chmod +x *.sh
$ sudo ./update.sh
```

## Uninstall:
```
$ cd /usr/src/ServiceSentry
$ sudo ./uninstall.sh
```

* Note: If no parameter is specified "/etc/ServiceSentry" is not erased. If you want a full uninstall must add the "-a" parameter.
* Note: on uninstall, dependencies aren't removed. **You must remove by hand**.
