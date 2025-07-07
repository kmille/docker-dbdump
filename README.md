# docker-dbdump - database backup for docker containers

This python script creates backups of databases which run in Docker containers. Please create an issue if you run into problems.

## How does it work?
1) Iterate over all running Docker containers
2) Check if it's a database container (MySQL, MariaDB, PostgreSQL, PostgriSQL)
3) If so, run mysqldump or the equivalent
4) Use `-v`/`--verbose`, it's helpful

## Features

- Backups all database containers, a few specified ones or all containers with some exceptions
- Creates [rsyncable](https://beeznest.wordpress.com/2005/02/03/rsyncable-gzip/) zip files (can be disabled with `--skip-gzip`)
- Creates a state file (useful for monitoring) with `--update-state-file`
- Always returns with exit code 0 unless you specify `--fail`

## Getting started

Please check the `docker-compose.yml` in the repo. It spawns some db containers and creates a backup. Use `docker-dbdump -h` for more information.

```
vim docker-compose.yml
sudo docker-compose up
```

## Installation

using [pip](https://pypi.org/project/docker-dbdump/):

```
pip install docker-dbdump
```

Using [docker](https://github.com/users/kmille/packages/container/package/docker-dbdump):

```
docker pull ghcr.io/kmille/docker-dbdump:latest
```

**Warning**: When using the docker image, you have to mount the Docker socket (`-v /var/run/docker.sock:/var/run/docker.sock`).

Using docker-compose:

```yaml
services: 
  docker-dbdump:
    image: ghcr.io/kmille/docker-dbdump:latest
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /backups:/backups
    command: "docker-dbdump --all --verbose"
```

Use `docker-compose -f /opt/container-backups/docker-compose.yml up` in cronjobs.

## dev environment
```bash
sudo docker-compose up # run some DB container
sudo poetry install

kmille@linbox:docker-dbdump sudo poetry run docker-dbdump -h
usage: [-h] [-v] [--backup-dir BACKUP_DIR] [-l [LIST]] [-a] [-b BACKUP [BACKUP ...]] [-i IGNORE_CONTAINER [IGNORE_CONTAINER ...]] [--skip-gzip] [-s] [--fail] [--version]

options:
  -h, --help            show this help message and exit
  -v, --verbose         print verbose output. Warning! This logs database passwords!
  --backup-dir BACKUP_DIR
                        output directory for backups
  -l, --list [LIST]     show running docker containers. Add argument to grep
  -a, --all             backup all running db containers
  -b, --backup BACKUP [BACKUP ...]
                        only backup specific containers
  -i, --ignore-container IGNORE_CONTAINER [IGNORE_CONTAINER ...]
                        backup all running db containers except the ones specified (can be used multiple times)
  --skip-gzip           Do not create create rsyncable gzip dump
  -s, --update-state-file
                        update state file (/var/log/docker-dbdump.done) with current date if everything succeeds
  --fail                if --fail is specified, the script will return with exit code 1 if an error occurs. If not specified, the exit code is always 0
  --version             print version and exit
```

**Note**: If you use `--ignore-container` option multiple times, please use the format `-i container1 container2`.

## Example output

```bash
kmille@linbox:docker-dbdump sudo poetry run docker-dbdump -l
docker-dbdump-maria-db-1       mariadb:11.2.2                 /home/kmille/projects/docker-dbdump
docker-dbdump-postgres-db-1    postgres:latest                /home/kmille/projects/docker-dbdump
docker-dbdump-postgis-db-1     postgis/postgis:latest         /home/kmille/projects/docker-dbdump
docker-dbdump-mysql-db-1       mysql:latest                   /home/kmille/projects/docker-dbdump

kmille@linbox:docker-dbdump sudo poetry run docker-dbdump -l maria
docker-dbdump-maria-db-1       mariadb:11.2.2                 /home/kmille/projects/docker-dbdump

kmille@linbox:docker-dbdump sudo poetry run docker-dbdump --all --verbose --update-state-file
[2025-02-23 09:48:43,156 DEBUG] Dumping backups to /backups
[2025-02-23 09:48:43,172 INFO] Starting to backup container docker-dbdump-postgis-db-1 (postgres)
[2025-02-23 09:48:43,172 DEBUG] Running dump 'docker exec b94ef9366188a5ede0187f92b48f733e9bdbb88be28e9453acccb45343ea2a7d pg_dumpall --username 'test-user' | gzip --rsyncable > /backups/_home_kmille_projects_docker-dbdump_docker-dbdump-postgis-db-1_test-user_postgres.sql.gz'
[2025-02-23 09:48:44,056 DEBUG] Sucessfully dumped backup
[2025-02-23 09:48:44,056 DEBUG] Checking backup with '['zgrep', '-q', '--', 'PostgreSQL database cluster dump', '/backups/_home_kmille_projects_docker-dbdump_docker-dbdump-postgis-db-1_test-user_postgres.sql.gz']'
[2025-02-23 09:48:44,067 DEBUG] Created backup looks good
[2025-02-23 09:48:44,067 INFO] Done backuping container docker-dbdump-postgis-db-1 (postgres)
[2025-02-23 09:48:44,070 INFO] Starting to backup container docker-dbdump-postgres-db-1 (postgres)
[2025-02-23 09:48:44,070 DEBUG] Running dump 'docker exec 3c6c7c220d34182d846127ea09fae1d2bd88b3ccd341a471eca8787522d782ed pg_dumpall --username 'postgres' | gzip --rsyncable > /backups/_home_kmille_projects_docker-dbdump_docker-dbdump-postgres-db-1_postgres_postgres.sql.gz'
[2025-02-23 09:48:44,399 DEBUG] Sucessfully dumped backup
[2025-02-23 09:48:44,399 DEBUG] Checking backup with '['zgrep', '-q', '--', 'PostgreSQL database cluster dump', '/backups/_home_kmille_projects_docker-dbdump_docker-dbdump-postgres-db-1_postgres_postgres.sql.gz']'
[2025-02-23 09:48:44,409 DEBUG] Created backup looks good
[2025-02-23 09:48:44,410 INFO] Done backuping container docker-dbdump-postgres-db-1 (postgres)
[2025-02-23 09:48:44,412 INFO] Starting to backup container docker-dbdump-maria-db-1 (mariadb)
[2025-02-23 09:48:44,412 DEBUG] Running dump 'docker exec 91dafc7f3a3a7fdeec5bd3993df5bb96fac2a6e9b5334c8e3b4d6dcac5a39d58 mariadb-dump -u 'root' -p'mariadb-root-password' --single-transaction --skip-lock-tables --all-databases | gzip --rsyncable > /backups/_home_kmille_projects_docker-dbdump_docker-dbdump-maria-db-1_root_mariadb.sql.gz'
[2025-02-23 09:48:44,906 DEBUG] Sucessfully dumped backup
[2025-02-23 09:48:44,907 DEBUG] Checking backup with '['zgrep', '-q', '-i', '--', '^-- mariadb dump', '/backups/_home_kmille_projects_docker-dbdump_docker-dbdump-maria-db-1_root_mariadb.sql.gz']'
[2025-02-23 09:48:44,919 DEBUG] Checking backup with '['zgrep', '-q', '--', '^-- Host: localhost', '/backups/_home_kmille_projects_docker-dbdump_docker-dbdump-maria-db-1_root_mariadb.sql.gz']'
[2025-02-23 09:48:44,930 DEBUG] Created backup looks good
[2025-02-23 09:48:44,931 INFO] Done backuping container docker-dbdump-maria-db-1 (mariadb)
[2025-02-23 09:48:44,933 INFO] Starting to backup container docker-dbdump-mysql-db-1 (mysql)
[2025-02-23 09:48:44,933 DEBUG] Running dump 'docker exec 6482f3ed4c47ebaae9289614adcacdef92ee66f4581c5d1cc2e726d66ac0ae1c mysqldump -u 'root' -p'mysql-root-password' --single-transaction --skip-lock-tables --all-databases | gzip --rsyncable > /backups/_home_kmille_projects_docker-dbdump_docker-dbdump-mysql-db-1_root_mysql.sql.gz'
[2025-02-23 09:48:45,546 DEBUG] Sucessfully dumped backup
[2025-02-23 09:48:45,546 DEBUG] Checking backup with '['zgrep', '-q', '-i', '--', '^-- mysql dump', '/backups/_home_kmille_projects_docker-dbdump_docker-dbdump-mysql-db-1_root_mysql.sql.gz']'
[2025-02-23 09:48:45,558 DEBUG] Checking backup with '['zgrep', '-q', '--', '^-- Host: localhost', '/backups/_home_kmille_projects_docker-dbdump_docker-dbdump-mysql-db-1_root_mysql.sql.gz']'
[2025-02-23 09:48:45,570 DEBUG] Created backup looks good
[2025-02-23 09:48:45,570 INFO] Done backuping container docker-dbdump-mysql-db-1 (mysql)
[2025-02-23 09:48:45,571 INFO] Updated state file /var/log/docker-dbdump.done
[2025-02-23 09:48:45,571 INFO] Everything worked fine. Exiting with exit code 0.

kmille@linbox:docker-dbdump cat /var/log/docker-dbdump.done
2025-02-23 09:48:45.570701
kmille@linbox:docker-dbdump ls -l /var/log/docker-dbdump.done
-rw-r--r-- 1 root root 27 Feb 23 09:48 /var/log/docker-dbdump.done

root@linbox: file /backups/_home_kmille_projects_docker-dbdump_docker-dbdump-*
/backups/_home_kmille_projects_docker-dbdump_docker-dbdump-maria-db-1_root_mariadb.sql.gz:         gzip compressed data, from Unix, original size modulo 2^32 3210314
/backups/_home_kmille_projects_docker-dbdump_docker-dbdump-mysql-db-1_root_mysql.sql.gz:           gzip compressed data, from Unix, original size modulo 2^32 3763792
/backups/_home_kmille_projects_docker-dbdump_docker-dbdump-postgis-db-1_test-user_postgres.sql.gz: gzip compressed data, from Unix, original size modulo 2^32 11915
/backups/_home_kmille_projects_docker-dbdump_docker-dbdump-postgres-db-1_postgres_postgres.sql.gz: gzip compressed data, from Unix, original size modulo 2^32 1789
```
