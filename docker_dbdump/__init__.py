#!/usr/bin/env python3
import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import NoReturn

import docker  # needs: yum install python-docker or pip install docker

from docker_dbdump.backup import DBContainer

state_file = Path("/var/log/docker-dbdump.done")

FORMAT = "[%(asctime)s %(levelname)s] %(message)s"
logging.basicConfig(format=FORMAT, level=logging.INFO)

ERROR = False
EXIT_CODE_FAILURE = 0


def fail(e: Exception | str) -> NoReturn:
    logging.error(e)
    sys.exit(EXIT_CODE_FAILURE)


if os.geteuid() != 0:
    fail("Needs to be run as root")

try:
    client = docker.from_env()
except docker.errors.DockerException as e:
    fail(f"Could not access Docker socket. {e}")


def do_backup(container: docker.models.containers.Container, backup_dir: Path, skip_gzip: bool) -> None:
    try:
        dbc = DBContainer(container)
        if dbc.is_supported:
            dbc.backup(backup_dir, not skip_gzip)
        else:
            tags = ", ".join(container.image.tags)
            logging.debug(f"Skipping container {dbc.name}. Image not supported: {tags}")
    except KeyboardInterrupt:
        fail("Exiting...")
    except Exception as e:
        logging.error(f"An exception occured during the backup of '{container.name}'")
        logging.exception(e)
        # don't let it fail. Backup all others containers instead. Fail with exit code 1 in the end
        global ERROR
        ERROR = True


def print_running_containers(grep: str) -> NoReturn:
    # if grep is '*' show all containers (coming from argparse)
    containers = client.containers.list(filters={"status": "running"})
    for container in containers:
        filter_container = grep != "*"
        if filter_container and grep.lower() not in container.name.lower():
            continue
        docker_compose_base = container.attrs["Config"]["Labels"].get(
            "com.docker.compose.project.working_dir", "not run by docker-compose"
        )
        tags = ", ".join(container.image.tags)
        print(f"{container.name:<40} {tags:<40} {docker_compose_base}")
    sys.exit(0)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser("")
    parser.add_argument("-v", "--verbose", action="store_true", help="print verbose output. Warning! This logs database passwords!")
    parser.add_argument("--backup-dir", default="/backups", type=Path, help="output directory for backups")
    parser.add_argument(
        "-l", "--list", nargs="?", const="*", help="show running docker containers. Add argument to grep"
    )
    parser.add_argument("-a", "--all", action="store_true", help="backup all running db containers")
    parser.add_argument("-b", "--backup", nargs="+", help="only backup specific containers")
    parser.add_argument(
        "-i",
        "--ignore-container",
        help="backup all running db containers except the ones specified (can be used multiple times)",
        nargs="+",
    )
    parser.add_argument("--skip-gzip", action="store_true", help="Do not create create rsyncable gzip dump")
    parser.add_argument(
        "-s",
        "--update-state-file",
        action="store_true",
        help=f"update state file ({state_file}) with current date if everything succeeds",
    )
    parser.add_argument(
        "--fail",
        action="store_true",
        help="if --fail is specified, the script will return with exit code 1 if an error occurs. "
        "If not specified, the exit code is always 0",
    )
    parser.add_argument("--version", action="store_true", help="print version and exit")

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

    if args.version:
        from importlib.metadata import version
        print("docker-dbdump v" + version("docker_dbdump"))
        sys.exit(0)

    if args.fail:
        global EXIT_CODE_FAILURE
        logging.debug("Setting exit code in case of an error to 1")
        EXIT_CODE_FAILURE = 1

    if args.list:
        print_running_containers(args.list)
    elif args.backup:
        for container_name in args.backup:
            try:
                container = client.containers.get(container_name)
                do_backup(container, args.backup_dir, args.skip_gzip)
            except docker.errors.NotFound:
                logging.error(f"Could not find a running container with name '{container_name}'")
                global ERROR
                ERROR = True
    elif args.all or args.ignore_container:
        containers = client.containers.list(filters={"status": "running"})
        for container in containers:
            if args.ignore_container and container.name in args.ignore_container:
                logging.info(f"Ignoring container '{container.name}'")
            else:
                do_backup(container, args.backup_dir, args.skip_gzip)

    if ERROR:
        logging.error(f"There were problems. Exiting with exit code {EXIT_CODE_FAILURE}.")
        sys.exit(EXIT_CODE_FAILURE)
    else:
        if args.update_state_file:
            state_file.write_text(f"{datetime.now()}\n")
            logging.info(f"Updated state file {state_file}")
        logging.info("Everything worked fine. Exiting with exit code 0.")
        sys.exit(0)


if __name__ == "__main__":
    main()
