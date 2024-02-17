#!/usr/bin/env python3
from datetime import datetime
import os
import sys
import logging
from pathlib import Path
import argparse
import docker  # needs: yum install python-docker or pip install docker
import subprocess

from typing import NoReturn
from enum import Enum

state_file = Path("/var/log/docker-dbdump.done")

FORMAT = "[%(asctime)s %(levelname)s] %(message)s"
logging.basicConfig(format=FORMAT, level=logging.INFO)

ERROR = False
EXIT_CODE_FAILURE = 1
MYSQL_MARIADB_ARGUMENTS = "--single-transaction --skip-lock-tables --all-databases"


def fail(e: Exception | str) -> NoReturn:
    logging.error(e)
    sys.exit(EXIT_CODE_FAILURE)


if os.geteuid() != 0:
    fail("Needs to be run as root")

try:
    client = docker.from_env()
except docker.errors.DockerException as e:
    fail(e)


class DBType(Enum):
    NOT_SUPPORTED = -1
    MYSQL = 1
    MARIADB = 2
    POSTGRES = 3


class BackupError(Exception):
    pass


class DBContainer:
    container: docker.models.containers.Container
    name: str
    username: str | None
    password: str | None
    db_type: DBType
    docker_compose_base: str

    def __init__(self, container: docker.models.containers.Container) -> None:
        self.container = container
        self.name = container.name
        self._set_container_type()
        self._set_docker_compose_directory()
        self._parse_envs()

    def type(self) -> str:
        return self.db_type.name.lower()

    def _set_container_type(self) -> None:
        image_tags = " ".join(self.container.image.tags).lower()
        db_type = DBType.NOT_SUPPORTED

        if "mysql" in image_tags:
            db_type = DBType.MYSQL
        if "mariadb" in image_tags:
            db_type = DBType.MARIADB
        if "postgres" in image_tags:
            db_type = DBType.POSTGRES
        if "postgis" in image_tags:
            db_type = DBType.POSTGRES
        self.db_type = db_type
        self.is_supported = (db_type != DBType.NOT_SUPPORTED)

    def _set_docker_compose_directory(self) -> None:
        try:
            self.docker_compose_base = self.container.attrs['Config']['Labels']['com.docker.compose.project.working_dir'].replace("/", "_")
        except KeyError:
            logging.warning(f"Could not get working_dir of container {self.name}. Using {self.name}")
            self.docker_compose_base = self.name

    def _get_container_envs(self) -> dict[str, str]:
        env_list = self.container.attrs["Config"]["Env"]
        env_dict = {}
        for env in env_list:
            key, value = env.split("=", 1)
            env_dict[key] = value
        return env_dict

    def _parse_envs(self) -> None:
        self.username = None
        self.password = None
        env = self._get_container_envs()

        if self.db_type == DBType.POSTGRES:
            self.username = env.get("POSTGRES_USER", "postgres")
        else:
            if "MYSQL_USER" in env or "MARIADB_USER" in env:
                self.username = env.get("MYSQL_USER", self.username)
                self.username = env.get("MARIADB_USER", self.username)
                self.password = env.get("MYSQL_PASSWORD", self.password)
                self.password = env.get("MARIADB_PASSWORD", self.password)

            if "MYSQL_ROOT_PASSWORD" in env or "MARIADB_ROOT_PASSWORD" in env:
                self.username = "root"
                self.password = env.get("MYSQL_ROOT_PASSWORD", self.password)
                self.password = env.get("MARIADB_ROOT_PASSWORD", self.password)

            if not all([self.username, self.password]):
                raise BackupError(f"Could not find username/password in env:\n{env}")

    def backup(self, out_dir: Path) -> None:
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

    def _dump_to_file(self, exec_output: docker.models.containers.ExecResult, out_file: Path) -> None:
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
                raise BackupError(f"Could not create dump for container {self.name}:\n{content.strip()}")
        elif self.db_type == DBType.POSTGRES:
            if "PostgreSQL database cluster dump" not in content:
                raise BackupError(f"Could not create dump for container {self.name}:\n{content.strip()}")
        logging.debug("Created backup looks good")

    def _backup_postgres(self, out_file: Path) -> docker.models.containers.ExecResult:
        cmd = f"pg_dumpall --username {self.username}"
        logging.debug(f"Running: '{cmd}'")
        return self.container.exec_run(cmd, user="postgres", stream=True)

    def _backup_maria_mysql(self, out_file: Path) -> docker.models.containers.ExecResult:
        if self.db_type == DBType.MARIADB:
            cmd = f"mariadb-dump -u {self.username} {MYSQL_MARIADB_ARGUMENTS}"
        elif self.db_type == DBType.MYSQL:
            cmd = f"mysqldump -u {self.username} {MYSQL_MARIADB_ARGUMENTS}"
        logging.debug(f"Running: '{cmd}'")
        return self.container.exec_run(cmd, environment={"MYSQL_PWD": self.password}, stream=True)

    def _zip_backup(self, out_file: Path) -> None:
        try:
            subprocess.run(["gzip", "-f", "--rsyncable", out_file.as_posix()], check=True, capture_output=True)
            logging.debug("Sucessfully zipped backup")
        except subprocess.CalledProcessError as e:
            raise BackupError(f"Could not zip file: {e.stderr.decode()}") from e


def do_backup(container: docker.models.containers.Container, backup_dir: Path) -> None:
    try:
        dbc = DBContainer(container)
        if not dbc.is_supported:
            tags = ", ".join(container.image.tags)
            logging.debug(f"Skipping container {dbc.name} (not supported (tags: {tags}))")
            return
        dbc.backup(backup_dir)
    except Exception as e:
        logging.error(e)
        global ERROR
        ERROR = True


def print_running_containers(grep: str) -> NoReturn:
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
    parser.add_argument("-v", "--verbose",
                        action="store_true",
                        help="print verbose output")
    parser.add_argument("--backup-dir",
                        default="/backups",
                        type=Path,
                        help="output directory for backups")
    parser.add_argument("-l", "--list",
                        nargs="?",
                        const="*",
                        help="show running docker containers. Add argument to grep")
    parser.add_argument("-a", "--all",
                        action="store_true",
                        help="backup all running db containers")
    parser.add_argument("-b", "--backup",
                        nargs="+",
                        help="only backup specific containers")
    parser.add_argument("-i", "--ignore-container",
                        help="backup all running db containers except the ones specified (can be used multiple times)",
                        nargs="+")
    parser.add_argument("-s", "--update-state-file",
                        action="store_true",
                        help=f"update state file ({state_file}) with current date if everything succeeds")

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    return parser.parse_args()


def main() -> None:
    args = parse_arguments()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("urllib3").setLevel(logging.INFO)
        logging.getLogger("docker").setLevel(logging.INFO)

    logging.debug(f"Dumping backups to {args.backup_dir}")
    args.backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)

    if args.list:
        print_running_containers(args.list)
    elif args.backup:
        for container_name in args.backup:
            try:
                container = client.containers.get(container_name)
                do_backup(container, args.backup_dir)
            except docker.errors.NotFound:
                logging.error(f"Could not find a running container with name {container_name}")
                global ERROR
                ERROR = True
    elif args.all:
        containers = client.containers.list(filters={'status': "running"})
        for container in containers:
            do_backup(container, args.backup_dir)
    elif args.ignore_container:
        containers = client.containers.list(filters={'status': "running"})
        for container in containers:
            if container.name in args.ignore_container:
                logging.info(f"Ignoring container '{container.name}'")
            else:
                do_backup(container, args.backup_dir)

    if ERROR:
        logging.error(f"There were problems. Exiting with exit code {EXIT_CODE_FAILURE}.")
        sys.exit(EXIT_CODE_FAILURE)
    else:
        if args.update_state_file:
            state_file.write_text(f"{datetime.now()}\n")
            logging.info(f"Updated state file {state_file}")
        logging.info("Everything worked fine. Exiting with exit code 0.")
        sys.exit(0)


if __name__ == '__main__':
    main()
