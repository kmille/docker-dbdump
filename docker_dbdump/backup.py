from enum import Enum
from pathlib import Path
import subprocess
import logging

import docker  # needs: yum install python-docker or pip install docker

MYSQL_MARIADB_ARGUMENTS = "--single-transaction --skip-lock-tables --all-databases"


class BackupError(Exception):
    pass


class DBType(Enum):
    NOT_SUPPORTED = -1
    MYSQL = 1
    MARIADB = 2
    POSTGRES = 3


class DBContainer:
    container: docker.models.containers.Container
    name: str
    username: str | None
    password: str | None
    db_type: DBType
    docker_compose_base: str
    is_supported: bool

    def __init__(self, container: docker.models.containers.Container) -> None:
        self.container = container
        self.name = container.name
        self._set_container_type()
        if self.is_supported:
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
        self.is_supported = db_type != DBType.NOT_SUPPORTED

    def _set_docker_compose_directory(self) -> None:
        try:
            self.docker_compose_base = self.container.attrs["Config"]["Labels"][
                "com.docker.compose.project.working_dir"
            ].replace("/", "_")
        except KeyError:
            logging.warning(f"Could not get docker compose working directory. Using {self.name}")
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
                raise BackupError(f"Could not find username/password in env for container {self.name}:\n{env}")

    def backup(self, out_dir: Path, compress) -> None:
        filename = f"{self.docker_compose_base}_{self.name}" + \
                   f"_{self.username}_{self.type()}.sql{'.gz' if compress else ''}"
        out_file = out_dir / filename
        dockercmd = ""
        logging.info(f"Starting to backup container {self.name} ({self.type()})")

        if self.db_type in (DBType.MARIADB, DBType.MYSQL):
            if self.db_type == DBType.MARIADB:
                dockercmd = "mariadb-dump"
            elif self.db_type == DBType.MYSQL:
                dockercmd = "mysqldump"
            dockercmd += f" -u '{self.username}' -p'{self.password}' {MYSQL_MARIADB_ARGUMENTS}"
        elif self.db_type == DBType.POSTGRES:
            dockercmd = f"pg_dumpall --username '{self.username}'"
        else:
            raise BackupError(f"Unkown DB type {self.db_type}")

        cmd = f"docker exec {self.container.id} {dockercmd} {'| gzip --rsyncable' if compress else ''} > {out_file.as_posix()}"
        fullcmd = ["bash", "-c", cmd]
        try:
            logging.debug(f"Running dump '{cmd}'")
            subprocess.run(fullcmd, check=True, capture_output=True)
            logging.debug("Sucessfully dumped backup")
        except subprocess.CalledProcessError as e:
            logging.error(f"Backup cmd returned with {e.returncode}: {e.stderr.decode().strip()}")
            raise e

        out_file.chmod(0o600)
        self._check_backup(out_file)
        logging.info(f"Done backuping container {self.name} ({self.type()})")

    def _check_backup(self, out_file: Path) -> None:
        if not out_file.exists():
            raise BackupError(f"The backup file '{out_file}' does not exist")

        if self.db_type in (DBType.MYSQL, DBType.MARIADB):
            self._grep_str(f"^-- {self.type()} dump", out_file, ["-i"])
            self._grep_str("^-- Host: localhost", out_file)
        elif self.db_type == DBType.POSTGRES:
            self._grep_str("PostgreSQL database cluster dump", out_file)
        logging.debug("Created backup looks good")

    def _grep_str(self, string: str, file: Path, flags: list[str] = []):
        command = "zgrep" if file.suffix == ".gz" else "grep"
        cmd = [command, "-q"]
        cmd.extend(flags)
        cmd.extend(["--", string, str(file)])

        try:
            logging.debug(f"Checking backup with '{cmd}'")
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError:
            raise BackupError(f"Could not create dump for container {self.name}:\n{file}")
