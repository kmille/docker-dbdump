
DESC = f"""
Was macht dieses Skript?
1) nimmt sich alle laufenden Docker Container
2) Schaut, ob in dem image "postgres", "mysql" oder "mariadb" vorkommt
3) lässt pg_dumpall/mysqldump laufen und speichert die dumps nach {OUT_DIR}

Notes
- Dieses Script sollte vor dem eigentlichem Backup laufen
- UPDATE: Dieses Skript sollte nie failen! Also immer 0 zurück geben
- Am besten die .sql.gz files liegen lassen. Nicht dass beim Backup machen die Platte voll läuft
- Bitwarden (SQL Server) backupt seine Datenbank selbst (täglich um 0:00 Uhr nach /opt/bitwarden/bwdata/mssql/backups)


ISSUE
If we don't use stream=True in exec_run, the process gets out of memory by dumping big databases
But if we use stream=True, we can not get the return value, see: https://github.com/docker/docker-py/issues/1989
So I manually check if if the dump worked ...


Skript geschrieben von kamille

"""


CORNER_CASE_CONTAINER = [
    {
        "container_name": "icinga-db-1",
        "type": "mariadb",
        "container_dir": "/opt/icinga",
        "database": "icinga",
        "user": "root",
        "password": "funky",
    },
    {
        "container_name": "icinga-db-1",
        "type": "mariadb",
        "container_dir": "/opt/icinga",
        "database": "icingaweb2",
        "user": "icinga2",
        "password": "funky",
    },
    {
        "container_name": "secret-app",
        "type": "skip",  # Contains "postgres" in the image name but is not the DB container.
    },
    {
        "container_name": "mysqld-exporter",
        "type": "skip",  # Belongs to /opt/monitoring
    },
    {
        "container_name": "postgres-exporter",
        "type": "skip",  # Belongs to /opt/monitoring
    },
]
    try:
        OUT_DIR.mkdir(parents=True)
    except FileExistsError:
        pass

    containers = client.containers.list(filters={'status': "running"})
    if args and args.include_container:
        logging.info(f"Only dumping containers with '{args.include_container}' in the container name")
        for container in containers:
            if args.include_container in container.name:
                make_backup(container)

    elif args and args.exclude_container:
        for exclude in args.exclude_container:
            if len(exclude) != 1:
                fail("Only one container for -e is allowed. Use -e container1 -e container2")
        args.exclude_container = [e[0] for e in args.exclude_container]
        logging.info(f"Dumping containers which do not contain {args.exclude_container} in the name")
        for container in containers:
            if (
                "postgres" in str(container.image)
                or "postgis" in str(container.image)
                or "mysql" in str(container.image)
                or "mariadb" in str(container.image)
            ):
                if container.name in args.exclude_container:
                    logging.info(f"Skipping container {container.name}")
                else:
                    make_backup(container)

    else:
        logging.info("Dumping corner case containers")
        for cc in CORNER_CASE_CONTAINER:
            try:
                container = client.containers.get(cc['container_name'])
            except (docker.errors.NotFound, docker.errors.APIError):
                logging.warning(f"Container {cc['container_name']} not found")
                continue
            if cc["type"] == "skip":
                continue
            if container.status != "running":
                logging.warning(f"Container {cc['container_name']} is not running (state={container.status})")
                continue
            if cc["type"] == "postgres":
                container = client.containers.get(cc["container_name"])
                backup_postgres_container(cc["container_name"], cc["container_dir"], cc["user"])
            elif cc["type"] in ("mysql", "mariadb"):
                backup_mysql_container(
                    cc["container_name"],
                    cc["container_dir"],
                    cc["type"],
                    10,
                    cc["user"],
                    cc["password"],
                    cc["database"],
                )
            else:
                fail(f"invalid Type of corner case config:\n{CORNER_CASE_CONTAINER}")

        blacklist = [c["container_name"] for c in CORNER_CASE_CONTAINER]
        logging.info("Dumping all containers found by docker ps")
        for container in containers:
            if container.name in blacklist:
                logging.info(f"Skipping corner case container {container.name}")
                continue
            if "<Image: ''>" in str(container.image):
                logging.warning(
                    f"image tag has been deleted; please run `docker-compose up` for container {container.name}"
                )
            if (
                "postgres" in str(container.image)
                or "postgis" in str(container.image)
                or "mysql" in str(container.image)
                or "mariadb" in str(container.image)
            ):
                make_backup(container)
