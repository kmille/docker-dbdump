# docker-dbdump - database backup for docker

This tool makes backups of databases, which run in Docker containers. Please create an issue if you run into problems.

## How does it work?
1) Iterate over all running Docker containers
2) Check if it's a database container (MySQL, MariaDB, PostgreSQL, PostgriSQL)
3) If so, run mysqldump or the equivalent
4) Use `-v`/`--verbose`, it's helpful

## Features
- Creates [rsyncable](https://beeznest.wordpress.com/2005/02/03/rsyncable-gzip/) zip files
- Back up all database containers, a few specified ones or all containers with some exceptions
- Creates a state file (useful for monitoring)

## dev environment
```bash
sudo docker-compose up # runs some DB container
sudo poetry install

kmille@linbox:docker-dbdump sudo poetry run docker-dbdump -h
[sudo] password for kmille:
usage: [-h] [-v] [--backup-dir BACKUP_DIR] [-l [LIST]] [-a] [-b BACKUP [BACKUP ...]] [-i IGNORE_CONTAINER [IGNORE_CONTAINER ...]] [-s]

options:
  -h, --help            show this help message and exit
  -v, --verbose         print verbose output
  --backup-dir BACKUP_DIR
                        output directory for backups
  -l [LIST], --list [LIST]
                        show running docker containers. Add argument to grep
  -a, --all             backup all running db containers
  -b BACKUP [BACKUP ...], --backup BACKUP [BACKUP ...]
                        only backup specific containers
  -i IGNORE_CONTAINER [IGNORE_CONTAINER ...], --ignore-container IGNORE_CONTAINER [IGNORE_CONTAINER ...]
                        backup all running db containers except the ones specified (can be used multiple times)
  -s, --update-state-file
                        update state file (/var/log/docker-dbdump.done) with current date if everything succeeds
```

## Example run
```bash
kmille@linbox:docker-dbdump sudo poetry run docker-dbdump -l
docker-dbdump-maria-db-1       mariadb:11.2.2                 /home/kmille/projects/docker-dbdump
docker-dbdump-postgres-db-1    postgres:latest                /home/kmille/projects/docker-dbdump
docker-dbdump-postgis-db-1     postgis/postgis:latest         /home/kmille/projects/docker-dbdump
docker-dbdump-mysql-db-1       mysql:latest                   /home/kmille/projects/docker-dbdump

kmille@linbox:docker-dbdump sudo poetry run docker-dbdump -l maria
docker-dbdump-maria-db-1       mariadb:11.2.2                 /home/kmille/projects/docker-dbdump

kmille@linbox:docker-dbdump sudo poetry run docker-dbdump --all --update-state-file
[2024-02-15 21:52:05,368 INFO] Starting to backup container docker-dbdump-maria-db-1 (mariadb)
[2024-02-15 21:52:05,933 INFO] Done backuping container docker-dbdump-maria-db-1 (mariadb)
[2024-02-15 21:52:05,936 INFO] Starting to backup container docker-dbdump-postgres-db-1 (postgres)
[2024-02-15 21:52:06,244 INFO] Done backuping container docker-dbdump-postgres-db-1 (postgres)
[2024-02-15 21:52:06,248 INFO] Starting to backup container docker-dbdump-postgis-db-1 (postgres)
[2024-02-15 21:52:07,013 INFO] Done backuping container docker-dbdump-postgis-db-1 (postgres)
[2024-02-15 21:52:07,016 INFO] Starting to backup container docker-dbdump-mysql-db-1 (mysql)
[2024-02-15 21:52:07,744 INFO] Done backuping container docker-dbdump-mysql-db-1 (mysql)
[2024-02-15 21:52:07,744 INFO] Updated state file /var/log/docker-dbdump.done
[2024-02-15 21:52:07,744 INFO] Everything worked fine. Exiting with exit code 0.

kmille@linbox:docker-dbdump sudo poetry run docker-dbdump --backup docker-dbdump-postgres-db-1 --verbose
[2024-02-15 21:54:16,903 DEBUG] Dumping backups to /backups
[2024-02-15 21:54:16,908 INFO] Starting to backup container docker-dbdump-postgres-db-1 (postgres)
[2024-02-15 21:54:16,908 DEBUG] Running: 'pg_dumpall --username postgres'
[2024-02-15 21:54:17,187 DEBUG] Created backup looks good
[2024-02-15 21:54:17,190 DEBUG] Sucessfully zipped backup
[2024-02-15 21:54:17,191 DEBUG] Sucessfully wrote backup to /backups/_home_kmille_projects_docker-dbdump_docker-dbdump-postgres-db-1_postgres_postgres.sql.gz
[2024-02-15 21:54:17,191 INFO] Done backuping container docker-dbdump-postgres-db-1 (postgres)
[2024-02-15 21:54:17,191 INFO] Everything worked fine. Exiting with exit code 0.
```
