#!/usr/bin/env python3
from datetime import datetime
import os
import sys
import logging
from pathlib import Path
import argparse
import docker  # needs: yum install python-docker or pip install docker
import subprocess


import shutil
from enum import Enum

BINARIES = ["mariadb-dump", "mysqldump", "pg_dumpall", "gzip"]

#OUT_DIR = Path("/backups/db-dumps/container")
state_file = Path("/var/log/sqldump-backup.done")

FORMAT = "[%(asctime)s %(levelname)s] %(message)s"
logging.basicConfig(format=FORMAT, level=logging.INFO)


class DBType(Enum):
    NOT_SUPPORTED = -1
    MYSQL = 1
    MARIADB = 2
    POSTGRES = 3


def fail(e, exception=False):
    if exception:
        logging.exception(e)
    else:
        logging.error(e)
    sys.exit(0)


def check_binaries():
    for binary in BINARIES:
        if not shutil.which(binary):
            fail(f"Utility '{binary}' not found. Please install it")


class DBContainer:
    container: docker.models.containers.Container
    name: str
    username: str
    password: str
    database: str
    db_type: DBType
    docker_compose_base: str

    def __init__(self, container: docker.models.containers.Container):
        self.container = container
        self.name = container.name
        self._set_container_type()
        self._set_docker_compose_directory()
        self._parse_envs()

    def type(self):
        return self.db_type.name.lower()

    def _set_container_type(self):
        image_tags = " ".join(self.container.image.tags).lower()
        db_type = DBType.NOT_SUPPORTED

        if "mysql" in image_tags:
            db_type = DBType.MYSQL
        if "mariadb" in image_tags:
            db_type = DBType.MARIADB
        if "postgres" in image_tags:
            db_type = DBType.POSTGRES
        self.db_type = db_type
        self.is_supported = (db_type != DBType.NOT_SUPPORTED)

    def _set_docker_compose_directory(self):
        try:
            self.docker_compose_base = self.container.attrs['Config']['Labels']['com.docker.compose.project.working_dir'].replace("/", "_")
        except KeyError:
            logging.warning(f"Could not get working_dir of container {self.name}. Using {self.container_dir}")
            self.docker_compose_base = self.container.name

    def _get_container_envs(self) -> dict[str, str]:
        env_list = self.container.attrs["Config"]["Env"]
        env_dict = {}
        for env in env_list:
            key, value = env.split("=", 1)
            env_dict[key] = value
        return env_dict

    def _parse_envs(self):
        self.username = None
        self.password = None
        self.database = None
        env = self._get_container_envs()

        if self.db_type == DBType.POSTGRES:
            self.username = env.get("POSTGRES_USER", "postgres")
        else:
            # we don't need the database name if we backup postgres
            self.database = env.get("MYSQL_DATABASE", self.database)
            self.database = env.get("MARIADB_DATABASE", self.database)

            if "MYSQL_USER" in env or "MARIADB_USER" in env:
                self.username = env.get("MYSQL_USER", self.username)
                self.username = env.get("MARIADB_USER", self.username)
                self.password = env.get("MYSQL_PASSWORD", self.password)
                self.password = env.get("MARIADB_PASSWORD", self.password)

            if "MYSQL_ROOT_PASSWORD" in env or "MARIADB_ROOT_PASSWORD" in env:
                self.username = "root"
                self.password = env.get("MYSQL_ROOT_PASSWORD", self.password)
                self.password = env.get("MARIADB_ROOT_PASSWORD", self.password)

        # TODO: find something smarter
        #if not all([self.database, self.username, self.password]):
        #    fail(f"Could not get credentials of container {self.name} (wrong envs)\nCurrent values: ",
        #         f"{self.username=} {self.password=} {self.database=}\nContainer env:\n{env}")

    def backup(self, out_dir: Path):
        filename = self.docker_compose_base + "_" + self.name + f"_{self.username}_{self.type()}.sql"
        out_file = out_dir / filename
        logging.info(f"Starting to backup container {self.name} ({self.type()})")

        if self.db_type in (DBType.MARIADB, DBType.MYSQL):
            exec_output = self._backup_maria_mysql(out_file)
        elif self.db_type == DBType.POSTGRES:
            exec_output = self._backup_postgres(out_file)

        self._dump_to_file(exec_output, out_file)
        self._check_backup(out_file)
        self._zip_backup(out_file)
        logging.debug(f"Sucessfully wrote backup to {out_file}.gz")
        logging.info(f"Done backuping container {self.name} ({self.type()})")

    def _dump_to_file(self, exec_output, out_file: Path):
        with out_file.open("wb") as f:
            for data in exec_output.output:
                f.write(data)
        out_file.chmod(0o600)

    def _check_backup(self, out_file: Path) -> None:
        with out_file.open("rb") as f:
            content = f.read(300).decode()
        if self.db_type in (DBType.MYSQL, DBType.MARIADB):
            if not content.lower().startswith(f"-- {self.type()} dump") and \
                    "Host: localhost" not in content:
                fail(f"Could not create dump for container {self.name}:\nContent:\n{content}\nfile: {out_file}")
        elif self.db_type == DBType.POSTGRES:
            if "PostgreSQL database cluster dump" not in content:
                fail(f"Could not create dump for container {self.name}:\nContent:\n{content}\nfile: {out_file}")
        logging.debug("Created backup looks good")

    def _backup_postgres(self, out_file: Path):
        cmd = f"pg_dumpall --username {self.username}"
        logging.debug(f"Running: '{cmd}'")
        return self.container.exec_run(cmd, user="postgres", stream=True)

    def _backup_maria_mysql(self, out_file: Path) -> None:
        # TODO: add --no-tablespaces ?
        if self.db_type == DBType.MARIADB:
            cmd = f'mariadb-dump -u {self.username} -p"{self.password}" --no-tablespaces --all-databases --system=all'
        elif self.db_type == DBType.MYSQL:
            cmd = f"mysqldump -u {self.username} --single-transaction --skip-lock-tables --all-databases"
        logging.debug(f"Running: '{cmd}'")
        return self.container.exec_run(cmd, environment={"MYSQL_PWD": self.password}, stream=True)

    def _zip_backup(self, out_file: Path) -> None:
        try:
            subprocess.run(["gzip", "-f", "--rsyncable", out_file.as_posix()], check=True, capture_output=True)
            logging.debug("Sucessfully zipped backup")
        except subprocess.CalledProcessError as e:
            logging.error(f"Could not zip file {out_file}")
            fail(e.stderr.decode())


def do_backup(container: docker.models.containers.Container):
    backup_dir = Path("/backups")
    dbc = DBContainer(container)
    if not dbc.is_supported:
        logging.debug(f"Skipping container {dbc.name} (no db container/not supported")
        return
    dbc.backup(backup_dir)


def print_running_containers(grep: str):
    client = docker.from_env()
    containers = client.containers.list(filters={'status': "running"})
    for container in containers:
        if grep != "*" and grep not in container.name:
            continue
        docker_compose_base = container.attrs['Config']['Labels'].get('com.docker.compose.project.working_dir', "not run by docker-compose")
        tags = ", ".join(container.image.tags)
        print(f"{container.name:<30} {tags:<30} {docker_compose_base}")
    sys.exit(0)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser("")
    parser.add_argument("-l", "--list",
                        nargs="?",
                        const="*",
                        help="show running docker containers. Add argument to grep")
    parser.add_argument("-e", "--exclude-container",
                        help="exclude a specific container (can be used multiple times)",
                        action="append",
                        nargs="+")
    parser.add_argument("-b", "--backup",
                        nargs="+",
                        help="only backup specific containers")
    parser.add_argument("-a", "--all",
                        action="store_true",
                        help="backup all running db containers")
    parser.add_argument("-v", "--verbose",
                        action="store_true",
                        help="print verbose output")

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    return parser.parse_args()


def main():
    if os.geteuid() != 0:
        fail("Needs to be run as root")

    args = parse_arguments()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("urllib3").setLevel(logging.INFO)
        logging.getLogger("docker").setLevel(logging.INFO)
    if args.list:
        print_running_containers(args.list)

    check_binaries()
    client = docker.from_env()

    def get_running_container_names():
        return [c.name for c in client.containers.list(filters={'status': "running"})]

    if args.backup:
        # first check if all containers are running before starting backuping
        for container_name in args.backup:
            if container_name not in get_running_container_names():
                fail(f"Could not find running container '{container_name}'")

        for container_name in args.backup:
            container = client.containers.get(container_name)
            do_backup(container)

    elif args.all:
        containers = client.containers.list(filters={'status': "running"})
        for container in containers:
            if "postgres" in container.name:
                do_backup(container)


if __name__ == '__main__':
    main()

    try:
        main()
        #state_file.write_text(f"{datetime.now()}\n")
        #logging.info(f"Wrote date to {state_file}")
    except Exception as e:
        raise
        logging.error(e)
        sys.exit(0)
