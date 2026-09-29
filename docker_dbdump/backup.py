from enum import Enum
from pathlib import Path
import subprocess
import logging

import docker  # needs: apt install python3-docker or pip install docker

LABEL_PREFIX = "docker-dbdump."
MYSQL_MARIADB_ARGUMENTS = ["--single-transaction", "--skip-lock-tables", "--all-databases", "--routines", "--events"]


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
    labels: dict

    def __init__(self, container: docker.models.containers.Container) -> None:
        self.container = container
        self.name = container.name
        self._set_container_type()
        if self.is_supported:
            self._set_docker_compose_directory()
            self.labels = container.attrs["Config"].get("Labels") or {}

    def type(self) -> str:
        return self.db_type.name.lower()

    def _set_container_type(self) -> None:
        image_tags = " ".join(self.container.image.tags).lower()
        self.db_type = DBType.NOT_SUPPORTED

        if "mysql" in image_tags:
            self.db_type = DBType.MYSQL
        elif "mariadb" in image_tags:
            self.db_type = DBType.MARIADB
        elif "postgres" in image_tags:
            self.db_type = DBType.POSTGRES
        elif "postgis" in image_tags:
            self.db_type = DBType.POSTGRES
        self.is_supported = self.db_type != DBType.NOT_SUPPORTED

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

    def _apply_label_overrides(self) -> None:
        username_override = self.labels.get(f"{LABEL_PREFIX}username")
        password_override = self.labels.get(f"{LABEL_PREFIX}password")

        if username_override:
            logging.info(f"Overriding username '{username_override}' for {self.name} via label")
            self.username = username_override
        if password_override:
            logging.info(f"Overriding password for {self.name} via label")
            self.password = password_override

    def _parse_envs(self) -> None:
        self.username = None
        self.password = None

        if f"{LABEL_PREFIX}username" in self.labels.keys():
            self._apply_label_overrides()
            return

        env = self._get_container_envs()
        if self.db_type == DBType.POSTGRES:
            self.username = env.get("POSTGRES_USER", "postgres")
        else:
            if "MYSQL_USER" in env or "MARIADB_USER" in env:
                self.username = env.get("MYSQL_USER", env.get("MARIADB_USER", None))
                self.password = env.get("MYSQL_PASSWORD", env.get("MARIADB_PASSWORD", None))

            if "MYSQL_ROOT_PASSWORD" in env or "MARIADB_ROOT_PASSWORD" in env:
                self.username = "root"
                self.password = env.get("MYSQL_ROOT_PASSWORD", env.get("MARIADB_ROOT_PASSWORD", None))

            if not all([self.username, self.password]):
                raise BackupError(f"Could not find username/password in env for container {self.name}:\n{env}")

    def backup(self, out_dir: Path, compress: bool) -> None:
        logging.info(f"Backuping container {self.name} ({self.type()})")
        self._parse_envs()
        if self.db_type in (DBType.MARIADB, DBType.MYSQL):
            if self.db_type == DBType.MARIADB:
                backup_cmd = ["mariadb-dump", ]
            elif self.db_type == DBType.MYSQL:
                backup_cmd = ["mysqldump", ]
            backup_cmd.extend(["-u", self.username, f"-p{self.password}", *MYSQL_MARIADB_ARGUMENTS])
        elif self.db_type == DBType.POSTGRES:
            backup_cmd = ["pg_dumpall", "--username", self.username]
        else:
            raise BackupError(f"Unkown DB type {self.db_type}")

        out_file = out_dir / f"{self.docker_compose_base}_{self.name}_{self.username}_{self.type()}.sql"

        # we don't use the docker python module here, we can use stream=True XOR get return value
        cmd = ["docker", "exec", self.container.id] + backup_cmd
        logging.debug(f"Executing '{" ".join(cmd)}'")
        try:
            with out_file.open("wb") as f:
                subprocess.run(cmd, check=True, stdout=f, stderr=subprocess.PIPE)
            out_file.chmod(0o600)
            logging.debug(f"Successfully created dump of container {self.name}")
            self._check_backup(out_file)
        except subprocess.CalledProcessError as e:
            raise BackupError(f"Failed to create backup (return_code={e.returncode}): {e.stderr.decode().strip()}")

        if compress:
            try:
                subprocess.run(["gzip", "--rsyncable", "--force", out_file.as_posix()], check=True, stderr=subprocess.PIPE)
                logging.debug(f"Successfully zipped backup of container {self.name}")
            except subprocess.CalledProcessError as e:
                raise BackupError(f"Failed to gzip backup (return_code={e.returncode}): {e.stderr.decode().strip()}")
        logging.info(f"Done with {self.name}. Saved backup to {out_file}{".gz" if compress else ""}")

    def _check_backup(self, out_file: Path) -> None:
        if not out_file.exists():
            raise BackupError(f"The backup file '{out_file}' does not exist")
        if out_file.stat().st_size == 0:
            raise BackupError(f"The backup file '{out_file}' is empty")

        with out_file.open("r") as f:
            backup_header = f.read(128)

        if self.db_type in (DBType.MYSQL, DBType.MARIADB):
            if f"-- {self.type()} dump".lower() not in backup_header.lower():
                raise BackupError(f"Could not verify backup, got:\n{backup_header.strip()}")
        elif self.db_type == DBType.POSTGRES:
            if "-- PostgreSQL database cluster dump" not in backup_header:
                raise BackupError(f"Could not verify backup, got:\n{backup_header.strip()}")
        logging.debug("Created backup looks good")
