#!/usr/bin/python3
"""Restricted root CLI backend; JSON is the only request and response format."""

import argparse
import fcntl
import grp
import json
import math
import os
from pathlib import Path
import pwd
import re
import select
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time


ROOT_DATA = Path("/var/lib/aidipanel/docker-data")
ROOT_SOCKET = Path("/run/docker.sock")
CGROUP_ROOT = Path("/sys/fs/cgroup")
MOUNTINFO = Path("/proc/self/mountinfo")
STATE_DIR = Path("/var/lib/aidipanel/docker-sites")
RUNTIME_DIR = Path("/var/lib/aidipanel/docker-runtime")
UNIT_DIR = Path("/etc/systemd/user")
SUBUID = Path("/etc/subuid")
SUBGID = Path("/etc/subgid")
ROOT_UID = 0
MAX_INPUT = 65536
MAX_OUTPUT = 1048576
MAX_LOGS = 65536
MAX_CONTAINERS = 256
MANAGED_LABEL = "io.aidipanel.managed"
SCOPE_LABEL = "io.aidipanel.scope"
NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,62}\Z")
IMAGE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:@-]{0,254}\Z")
ID_PATTERN = re.compile(r"[a-f0-9]{12,64}\Z")
ACTIONS = ("status", "list", "create", "start", "stop", "restart", "remove", "logs", "enable", "disable")
CLEAN_ENVIRONMENT = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}


class ManagerError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise ManagerError(message)


def run_command(arguments, input_data=b"", timeout=30, output_limit=MAX_OUTPUT, merge_output=False, stdin_uid=None):
    process = None
    input_stream = None
    read_fd = None
    collected = bytearray()
    total_output = 0
    try:
        if stdin_uid is not None:
            read_fd, write_fd = os.pipe()
            input_stream = os.fdopen(write_fd, "wb", buffering=0)
            os.fchown(read_fd, stdin_uid, -1)
        process = subprocess.Popen(arguments, stdin=read_fd if read_fd is not None else subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env=CLEAN_ENVIRONMENT,
                                   start_new_session=True, close_fds=True)
        if read_fd is not None:
            os.close(read_fd)
            read_fd = None
        else:
            input_stream = process.stdin
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as selector:
            for stream in (process.stdout, process.stderr):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            if input_data:
                os.set_blocking(input_stream.fileno(), False)
                selector.register(input_stream, selectors.EVENT_WRITE)
            else:
                input_stream.close()
            pending_input = memoryview(input_data)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                require(remaining > 0, "Docker operation timed out")
                for selected, events in selector.select(min(remaining, 0.5)):
                    stream = selected.fileobj
                    if events & selectors.EVENT_WRITE:
                        try:
                            written = os.write(stream.fileno(), pending_input[:65536])
                            pending_input = pending_input[written:]
                        except BrokenPipeError:
                            pending_input = memoryview(b"")
                        if not pending_input:
                            selector.unregister(stream)
                            stream.close()
                    else:
                        chunk = os.read(stream.fileno(), 65536)
                        if not chunk:
                            selector.unregister(stream)
                            continue
                        total_output += len(chunk)
                        require(total_output <= output_limit, "Docker operation exceeded its output limit")
                        if stream is process.stdout or merge_output:
                            collected.extend(chunk)
            remaining = deadline - time.monotonic()
            require(remaining > 0, "Docker operation timed out")
            require(process.wait(timeout=remaining) == 0, "Docker command failed; check the service and prerequisites")
        return collected.decode("utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        raise ManagerError("Docker command failed; check the service and prerequisites") from None
    finally:
        if read_fd is not None:
            os.close(read_fd)
        if input_stream is not None:
            input_stream.close()
        if process is not None:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=2)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()


def checked_json(value):
    def object_pairs(pairs):
        result = {}
        for key, item in pairs:
            require(key not in result, "Duplicate JSON keys are not allowed")
            result[key] = item
        return result

    def invalid_constant(value):
        raise ManagerError("JSON numbers must be finite")

    try:
        return json.loads(value, object_pairs_hook=object_pairs, parse_constant=invalid_constant)
    except (ValueError, RecursionError):
        raise ManagerError("Invalid JSON input or Docker response") from None


def safe_path(value):
    require(isinstance(value, str) and len(value) <= 4096 and re.fullmatch(r"/[A-Za-z0-9_./-]+", value), "Invalid local path")
    require(".." not in value.split("/") and "." not in value.split("/") and "//" not in value, "Path traversal is not allowed")
    return Path(value)


def no_symlinks(path):
    for candidate in [*reversed(path.parents), path]:
        require(not candidate.is_symlink(), "Symlink paths are not allowed")


def host_mounts():
    with MOUNTINFO.open(encoding="utf-8") as stream:
        information = stream.read(MAX_OUTPUT + 1)
    require(len(information) <= MAX_OUTPUT, "Host mount table exceeds the inspection limit")
    mounts = []
    for line in information.splitlines():
        fields = line.split()
        require(len(fields) >= 10, "Invalid host mount table")
        mounts.append(Path(re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), fields[4])))
    return mounts


def secure_directory(path, mode=0o700):
    no_symlinks(path)
    path.mkdir(parents=True, mode=mode, exist_ok=True)
    metadata = path.stat()
    require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == ROOT_UID and not metadata.st_mode & 0o022,
            "Docker management directory must be root-owned and not writable by other users")


def read_root_file(path, limit=MAX_OUTPUT):
    no_symlinks(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        metadata = os.fstat(descriptor)
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == ROOT_UID and not metadata.st_mode & 0o022,
                "Docker management file must be root-owned and not writable by other users")
        with os.fdopen(descriptor, "r", encoding="utf-8", closefd=False) as stream:
            result = stream.read(limit + 1)
        require(len(result.encode()) <= limit, "Docker management file is too large")
        return result
    finally:
        os.close(descriptor)


def write_root_file(path, content, mode=0o600):
    secure_directory(path.parent, 0o755 if path.parent == UNIT_DIR else 0o700)
    no_symlinks(path)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(descriptor)
    finally:
        os.close(descriptor)


def bounded_text(value, limit=512):
    return "".join(character for character in str(value) if character in "\n\t" or ord(character) >= 32 and ord(character) != 127)[:limit]


def open_directory(path):
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in path.parts[1:]:
            child_descriptor = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def redact(value, environment, limit):
    secrets = sorted({entry.partition("=")[2] for entry in environment if isinstance(entry, str) and "=" in entry and entry.partition("=")[2]}, key=len, reverse=True)
    if secrets:
        value = re.sub("|".join(re.escape(secret) for secret in secrets), "[redacted]", value)
    return bounded_text(value, limit).encode("utf-8")[:limit].decode("utf-8", errors="ignore")


class DockerManager:
    def __init__(self, scope, domain=None, user=None, home=None):
        require(os.geteuid() == 0, "Docker management requires the root CLI")
        require(scope in ("root", "site"), "Invalid Docker scope")
        self.scope = scope
        self.domain = domain
        self.user = user
        self.home = None
        self.uid = None
        self.gid = None
        if scope == "site":
            require(isinstance(domain, str) and len(domain) <= 253 and re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", domain), "Invalid trusted site domain")
            require(all(label and len(label) <= 63 and not label.startswith("-") and not label.endswith("-") for label in domain.split(".")), "Invalid trusted site domain")
            require(isinstance(user, str) and re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user), "Invalid trusted site user")
            self.home = safe_path(home)
            no_symlinks(self.home)
            try:
                account = pwd.getpwnam(user)
            except KeyError:
                raise ManagerError("Trusted site user does not exist") from None
            require(account.pw_uid >= 1000 and account.pw_gid != 0 and account.pw_dir == str(self.home), "Trusted site identity does not match its home")
            require(self.home.is_dir() and self.home.stat().st_uid in (ROOT_UID, account.pw_uid), "Invalid trusted site home ownership")
            require(self.home != Path("/") and self.home.parent != Path("/"), "Invalid trusted site home")
            self.uid = account.pw_uid
            self.gid = account.pw_gid
        else:
            require(domain is None and user is None and home is None, "Root scope does not accept site identity")
        self.identity = "root" if scope == "root" else "site:" + domain + ":" + str(self.uid)
        self.runtime_user = "apdock_" + str(self.uid) if scope == "site" else None
        self.runtime_home = RUNTIME_DIR / str(self.uid) if scope == "site" else None
        self.runtime_uid = None
        self.runtime_gid = None
        self.socket = "/var/run/docker.sock" if scope == "root" else None
        self.unit = "aidipanel-docker-" + str(self.uid) + ".service"
        self.storage = self.runtime_home if scope == "site" else None
        self.marker = STATE_DIR / (str(self.uid) + ".json")

    def user_command(self, arguments):
        require(self.runtime_uid is not None, "Site runtime identity is not verified")
        runtime = "/run/user/" + str(self.runtime_uid)
        return ["/usr/sbin/runuser", "--user", self.runtime_user, "--", "/usr/bin/env", "-i",
                "HOME=" + str(self.runtime_home), "USER=" + self.runtime_user, "LOGNAME=" + self.runtime_user,
                "PATH=" + CLEAN_ENVIRONMENT["PATH"], "LANG=C.UTF-8", "LC_ALL=C.UTF-8",
                "XDG_RUNTIME_DIR=" + runtime, "DBUS_SESSION_BUS_ADDRESS=unix:path=" + runtime + "/bus", *arguments]

    def docker(self, arguments, **options):
        self.validate_socket()
        config = str(self.storage / "cli") if self.scope == "site" else "/var/lib/aidipanel/docker-cli"
        command = ["/usr/bin/docker", "--config", config, "--host", "unix://" + self.socket, *arguments]
        if self.scope == "site":
            command = self.user_command(command)
            if "--env-file" in arguments:
                options["stdin_uid"] = self.runtime_uid
        return run_command(command, **options)

    def validate_socket(self):
        socket_path = Path(self.socket) if self.scope == "site" else ROOT_SOCKET
        no_symlinks(socket_path)
        if os.path.lexists(socket_path):
            metadata = socket_path.lstat()
            expected_owner = self.runtime_uid if self.scope == "site" else ROOT_UID
            require(stat.S_ISSOCK(metadata.st_mode) and metadata.st_uid == expected_owner and not metadata.st_mode & 0o002,
                    "Docker socket has unsafe type, ownership or permissions")
            if self.scope == "site":
                runtime = socket_path.parent.stat()
                require(runtime.st_uid == self.runtime_uid and not runtime.st_mode & 0o077, "Unsafe rootless runtime directory ownership or permissions")

    def info(self):
        information = checked_json(self.docker(["info", "--format", "{{json .}}"], timeout=10))
        require(isinstance(information, dict), "Invalid Docker information")
        if self.scope == "site":
            require("name=rootless" in information.get("SecurityOptions", []), "Site daemon must be rootless")
        return information

    def verify_data_root(self, information):
        if self.scope == "site":
            no_symlinks(self.storage)
            require(information.get("DockerRootDir") == str(self.storage / "data"),
                    "Site Docker data directory does not match the managed runtime")
        return information

    def resources_available(self, information, verify_delegation=True):
        require(information.get("CgroupDriver") == "systemd" and str(information.get("CgroupVersion")) == "2"
                and all(information.get(key) is True for key in ("MemoryLimit", "CpuCfsQuota", "PidsLimit")),
                "CPU, memory and PID limits require working cgroup v2 systemd delegation")
        if not verify_delegation:
            return
        require(information.get("SwapLimit") is True, "A finite memory and swap limit requires cgroup v2 swap accounting")
        controllers = CGROUP_ROOT / "cgroup.controllers"
        if self.scope == "site":
            controllers = CGROUP_ROOT / "user.slice" / ("user-" + str(self.runtime_uid) + ".slice") / ("user@" + str(self.runtime_uid) + ".service") / "cgroup.controllers"
        require(controllers.is_file() and {"cpu", "memory", "pids"} <= set(controllers.read_text().split()),
                "CPU, memory and PID limits require cgroup v2 controller delegation to the site user manager")

    def validate_existing_limits(self, container):
        configuration = container.get("HostConfig", {})
        for key, lower, upper in (("NanoCpus", 100000000, 32000000000), ("Memory", 16777216, 68719476736), ("PidsLimit", 16, 4096)):
            value = configuration.get(key)
            require(type(value) is int and lower <= value <= upper, "Managed container requires finite CPU, memory and PID resource limits")
        require(configuration.get("MemorySwap") == configuration["Memory"], "Managed container requires a finite swap resource limit")

    def inspect(self, identifier):
        require(isinstance(identifier, str) and ID_PATTERN.fullmatch(identifier), "Invalid managed container ID")
        response = checked_json(self.docker(["inspect", "--type", "container", identifier], timeout=10))
        require(isinstance(response, list) and len(response) == 1 and isinstance(response[0], dict), "Invalid Docker container response")
        container = response[0]
        require(isinstance(container.get("Id"), str) and re.fullmatch(r"[a-f0-9]{64}", container["Id"]) and container["Id"].startswith(identifier), "Docker returned an unexpected container ID")
        return container

    def managed(self, container):
        labels = container.get("Config", {}).get("Labels") or {}
        return labels.get(MANAGED_LABEL) == "true" and labels.get(SCOPE_LABEL) == self.identity

    def managed_container(self, identifier):
        container = self.inspect(identifier)
        require(self.managed(container), "Container is not managed in this Docker scope")
        if self.scope == "site":
            for mount in container.get("Mounts", []):
                name = mount.get("Name", "")
                prefix = self.volume_name("")
                require(mount.get("Type") == "volume" and name.startswith(prefix)
                        and NAME_PATTERN.fullmatch(name[len(prefix):]), "Container contains an unmanaged mount")
                self.verify_volume(name)
        return container

    def identifiers(self, managed_only=True):
        arguments = ["ps", "--all", "--quiet", "--no-trunc"]
        if managed_only:
            arguments += ["--filter", "label=" + MANAGED_LABEL + "=true", "--filter", "label=" + SCOPE_LABEL + "=" + self.identity]
        identifiers = self.docker(arguments, timeout=10, output_limit=MAX_CONTAINERS * 65 + 1).split()
        require(len(identifiers) <= MAX_CONTAINERS and all(re.fullmatch(r"[a-f0-9]{64}", identifier) for identifier in identifiers), "Too many containers or invalid container IDs")
        return identifiers

    def summary(self, container):
        configuration = container.get("Config", {})
        environment = configuration.get("Env") or []
        state = container.get("State", {}).get("Status", "unknown")
        if state not in ("created", "running", "paused", "restarting", "removing", "exited", "dead"):
            state = "unknown"
        ports = []
        for endpoint, bindings in (container.get("NetworkSettings", {}).get("Ports") or {}).items():
            if not re.fullmatch(r"[0-9]{1,5}/tcp", endpoint):
                continue
            for binding in bindings or []:
                if binding.get("HostIp") == "127.0.0.1" and re.fullmatch(r"[0-9]{1,5}", str(binding.get("HostPort", ""))):
                    ports.append({"host": int(binding["HostPort"]), "container": int(endpoint.split("/")[0])})
        return {"id": container["Id"], "name": redact(str(container.get("Name", "")).lstrip("/"), environment, 128),
                "image": redact(str(configuration.get("Image", "")), environment, 256),
                "state": state, "status": state, "ports": ports[:32]}

    def validate_mount(self, volume):
        if self.scope == "site":
            require(isinstance(volume, dict) and set(volume) == {"name", "target", "readonly"}
                    and type(volume["readonly"]) is bool and isinstance(volume["name"], str)
                    and NAME_PATTERN.fullmatch(volume["name"]), "Invalid named volume fields")
            target = safe_path(volume["target"])
            require(target != Path("/") and not any(target == forbidden or target.is_relative_to(forbidden) for forbidden in (Path("/proc"), Path("/sys"), Path("/dev"), Path("/run"), Path("/var/run"))) and not str(target).endswith(".sock"), "Unsafe container mount target")
            return "type=volume,src=" + self.volume_name(volume["name"]) + ",dst=" + str(target) + (",readonly" if volume["readonly"] else "")
        require(isinstance(volume, dict) and set(volume) == {"source", "target", "readonly"} and type(volume["readonly"]) is bool, "Invalid volume fields")
        source = safe_path(volume["source"])
        target = safe_path(volume["target"])
        base = self.home if self.scope == "site" else ROOT_DATA
        require(source.is_relative_to(base) and source != base.parent, "Bind source must stay inside the managed data directory")
        require(target != Path("/") and not any(target == forbidden or target.is_relative_to(forbidden) for forbidden in (Path("/proc"), Path("/sys"), Path("/dev"), Path("/run"), Path("/var/run"))) and not str(target).endswith(".sock"), "Unsafe container mount target")
        if self.storage:
            require(not (source == self.storage or source.is_relative_to(self.storage) or self.storage.is_relative_to(source)), "Mounts cannot expose the site's Docker runtime")
        no_symlinks(source)
        require(source.exists(), "Bind source must already exist")
        for mount in host_mounts():
            require(not (mount.is_relative_to(base) and (source.is_relative_to(mount) or mount.is_relative_to(source))),
                    "Host mount points cannot be exposed through bind sources")
        if self.scope == "root":
            for ancestor in [source, *source.parents]:
                metadata = ancestor.stat()
                require(metadata.st_uid == ROOT_UID and not metadata.st_mode & 0o022, "Root bind ancestors must be root-owned and not writable by other users")
                if ancestor == base:
                    break
        pending = [source]
        visited = 0
        while pending:
            candidate = pending.pop()
            visited += 1
            require(visited <= 10000, "Bind source exceeds the safe inspection limit")
            metadata = candidate.lstat()
            require(stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode), "Bind sources cannot contain symlinks, sockets or special files")
            require(not candidate.is_mount() or candidate == base, "Nested host mounts are not allowed")
            if self.scope == "root":
                require(metadata.st_uid == ROOT_UID and not metadata.st_mode & 0o022, "Root bind sources must be root-owned and not writable by other users")
            if stat.S_ISDIR(metadata.st_mode):
                require(len(candidate.relative_to(source).parts) <= 64, "Bind source is too deeply nested")
                with os.scandir(candidate) as entries:
                    for entry in entries:
                        pending.append(Path(entry.path))
                        require(len(pending) + visited <= 10000, "Bind source exceeds the safe inspection limit")
        return "type=bind,src=" + str(source) + ",dst=" + str(target) + (",readonly" if volume["readonly"] else "")

    def volume_name(self, name):
        return "aidipanel-" + str(self.uid) + "-" + name

    def verify_volume(self, name):
        result = checked_json(self.docker(["volume", "inspect", name], timeout=10))
        require(isinstance(result, list) and len(result) == 1 and isinstance(result[0], dict), "Invalid volume inspection")
        volume = result[0]
        labels = volume.get("Labels") or {}
        require(volume.get("Name") == name and volume.get("Driver") == "local"
                and volume.get("Options") in (None, {}) and labels.get(MANAGED_LABEL) == "true"
                and labels.get(SCOPE_LABEL) == self.identity, "Unsafe or unmanaged named volume")

    def prepare_volume(self, name):
        generated = self.volume_name(name)
        result = self.docker(["volume", "create", "--driver", "local", "--label", MANAGED_LABEL + "=true",
                              "--label", SCOPE_LABEL + "=" + self.identity, generated], timeout=30).strip()
        require(result == generated, "Docker returned an unexpected volume name")
        self.verify_volume(generated)

    def validate_create(self, payload):
        fields = {"name", "image", "environment", "ports", "volumes", "cpus", "memory_mb", "pids_limit"}
        require(isinstance(payload, dict) and not set(payload) - fields and {"name", "image"} <= set(payload), "Invalid create fields")
        require(isinstance(payload["name"], str) and NAME_PATTERN.fullmatch(payload["name"]), "Invalid container name")
        require(isinstance(payload["image"], str) and IMAGE_PATTERN.fullmatch(payload["image"]), "Invalid container image")
        cpus = payload.get("cpus", 1)
        memory = payload.get("memory_mb", 512)
        pids = payload.get("pids_limit", 128)
        require(type(cpus) in (int, float) and math.isfinite(cpus) and 0.1 <= cpus <= 32, "CPU limit must be finite and between 0.1 and 32")
        require(type(memory) is int and 16 <= memory <= 65536, "Memory limit must be an integer between 16 and 65536 MiB")
        require(type(pids) is int and 16 <= pids <= 4096, "PID limit must be an integer between 16 and 4096")
        environment = payload.get("environment", {})
        require(isinstance(environment, dict) and len(environment) <= 128, "Invalid environment object")
        lines = []
        for key, value in environment.items():
            require(isinstance(key, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", key) and isinstance(value, str) and not any(character in value for character in ("\x00", "\n", "\r")), "Invalid environment entry")
            lines.append(key + "=" + value + "\n")
        input_data = "".join(lines).encode("utf-8")
        require(len(input_data) <= 32768, "Environment exceeds the size limit")
        ports = payload.get("ports", [])
        volumes = payload.get("volumes", [])
        require(isinstance(ports, list) and len(ports) <= 32 and isinstance(volumes, list) and len(volumes) <= 16, "Too many ports or mounts")
        arguments = ["create", "--pull=missing", "--name", payload["name"], "--label", MANAGED_LABEL + "=true",
                     "--label", SCOPE_LABEL + "=" + self.identity, "--cpus", str(cpus), "--memory", str(memory * 1048576),
                     "--memory-swap", str(memory * 1048576), "--pids-limit", str(pids), "--security-opt", "no-new-privileges=true",
                     "--log-driver", "local", "--log-opt", "max-size=1m", "--log-opt", "max-file=2",
                     "--env-file", "/dev/stdin"]
        bound_ports = set()
        for port in ports:
            require(isinstance(port, dict) and set(port) == {"host", "container"}, "Invalid port fields")
            require(all(type(port[key]) is int and 1 <= port[key] <= 65535 for key in ("host", "container")), "Ports must be integers between 1 and 65535")
            require(port["host"] not in bound_ports, "Duplicate host port")
            bound_ports.add(port["host"])
            arguments += ["--publish", "127.0.0.1:" + str(port["host"]) + ":" + str(port["container"]) + "/tcp"]
        for volume in volumes:
            arguments += ["--mount", self.validate_mount(volume)]
        arguments += [payload["image"]]
        return arguments, input_data, {"NanoCpus": round(cpus * 1000000000), "Memory": memory * 1048576, "MemorySwap": memory * 1048576, "PidsLimit": pids}

    def socket_exists(self):
        return self.socket is not None and os.path.lexists(self.socket)

    def runtime_record(self):
        if not self.marker.exists() and not self.marker.is_symlink():
            return None
        record = checked_json(read_root_file(self.marker, MAX_INPUT))
        require(isinstance(record, dict) and all(record.get(key) == value for key, value in
                {"domain": self.domain, "user": self.user, "home": str(self.home), "uid": self.uid, "unit": self.unit}.items()),
                "Managed rootless runtime identity mismatch")
        require(record.get("version") == 2 and record.get("runtime_user") == self.runtime_user
                and record.get("runtime_home") == str(self.runtime_home)
                and type(record.get("runtime_uid")) is int and type(record.get("runtime_gid")) is int,
                "Legacy or invalid rootless runtime record")
        self.verify_runtime(record["runtime_uid"], record["runtime_gid"])
        return record

    def verify_runtime(self, uid, gid):
        try:
            account = pwd.getpwnam(self.runtime_user)
        except KeyError:
            raise ManagerError("Managed runtime account is missing") from None
        require(uid > 0 and uid != self.uid and gid > 0 and gid != self.gid and account.pw_uid == uid and account.pw_gid == gid
                and account.pw_dir == str(self.runtime_home) and account.pw_shell in ("/usr/sbin/nologin", "/sbin/nologin"),
                "Managed runtime account identity mismatch")
        require(sum(account_entry.pw_uid == uid for account_entry in pwd.getpwall()) == 1,
                "Managed runtime UID is shared")
        require(not any(self.runtime_user in group.gr_mem for group in grp.getgrall()),
                "Managed runtime account has supplementary groups")
        require(not any(group.gr_gid == gid and group.gr_name == "docker" for group in grp.getgrall()),
                "Managed runtime account cannot use the Docker group")
        groups = [group for group in grp.getgrall() if group.gr_gid == gid]
        require(len(groups) == 1 and groups[0].gr_name == self.runtime_user,
                "Managed runtime primary group is not dedicated")
        require(not any(account_entry.pw_uid != uid and account_entry.pw_gid == gid for account_entry in pwd.getpwall()),
                "Managed runtime primary group is shared")
        no_symlinks(self.runtime_home)
        for ancestor in self.runtime_home.parents:
            metadata = ancestor.stat()
            require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == ROOT_UID and not metadata.st_mode & 0o022,
                    "Managed runtime ancestors must be root-controlled")
        parent = self.runtime_home.parent.stat()
        require(parent.st_uid == ROOT_UID and stat.S_ISDIR(parent.st_mode) and stat.S_IMODE(parent.st_mode) == 0o711,
                "Unsafe managed runtime parent")
        metadata = self.runtime_home.stat()
        require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == uid and stat.S_IMODE(metadata.st_mode) == 0o700,
                "Managed runtime home is not private")
        self.runtime_uid, self.runtime_gid = uid, gid
        self.socket = "/run/user/" + str(uid) + "/docker.sock"

    def subordinate_ranges(self):
        allocations = []
        active_identifiers = {account.pw_uid for account in pwd.getpwall()} | {group.gr_gid for group in grp.getgrall()}
        for source in (SUBUID, SUBGID):
            records = []
            own = []
            for line in read_root_file(source).splitlines():
                if not line.strip() or line.startswith("#"):
                    continue
                fields = line.split(":")
                require(len(fields) == 3 and fields[0] and fields[1].isdigit() and fields[2].isdigit(), "Invalid subordinate-ID allocation file")
                beginning, count = int(fields[1]), int(fields[2])
                ending = beginning + count - 1
                require(beginning >= 65536 and count > 0 and ending <= 4294967294 and not any(beginning <= identifier <= ending for identifier in active_identifiers), "Unsafe subordinate-ID allocation")
                records.append((beginning, ending))
                if fields[0] in (self.runtime_user, str(self.runtime_uid)):
                    own.append((beginning, ending))
            records.sort()
            require(all(previous[1] < following[0] for previous, following in zip(records, records[1:])), "Overlapping subordinate-ID allocations")
            if own:
                require(any(ending - beginning + 1 >= 65536 for beginning, ending in own), "Site requires at least 65536 subordinate IDs")
                allocations.append(None)
                continue
            beginning = 100000
            reserved = sorted(records + [(identifier, identifier) for identifier in active_identifiers])
            for allocated_start, allocated_end in reserved:
                if beginning + 65535 < allocated_start:
                    break
                if beginning <= allocated_end:
                    beginning = allocated_end + 1
            require(beginning + 65535 <= 4294967294, "No safe subordinate-ID range is available")
            allocations.append(str(beginning) + "-" + str(beginning + 65535))
        return tuple(allocations)

    def prerequisites(self):
        binaries = ("/usr/bin/docker", "/usr/bin/dockerd-rootless.sh", "/usr/bin/rootlesskit", "/usr/bin/slirp4netns",
                    "/usr/bin/newuidmap", "/usr/bin/newgidmap", "/usr/bin/systemctl", "/usr/bin/loginctl", "/usr/sbin/runuser", "/usr/sbin/usermod", "/usr/sbin/useradd", "/usr/sbin/userdel")
        require(all(os.access(binary, os.X_OK) for binary in binaries), "Install signed Docker rootless extras, uidmap, slirp4netns and systemd prerequisites")
        for binary in ("/usr/bin/newuidmap", "/usr/bin/newgidmap"):
            metadata = Path(binary).stat()
            require(metadata.st_uid == ROOT_UID and bool(metadata.st_mode & stat.S_ISUID), "Rootless uidmap helpers must have their packaged root-owned setuid permissions")
        require(Path("/run/systemd/system").is_dir(), "Rootless Docker requires a running systemd user manager")
        require({"cpu", "memory", "pids"} <= set((CGROUP_ROOT / "cgroup.controllers").read_text().split()), "Rootless Docker requires cgroup v2 CPU, memory and PID controllers")
        for setting in ("/proc/sys/kernel/unprivileged_userns_clone", "/proc/sys/user/max_user_namespaces"):
            if Path(setting).exists():
                require(int(Path(setting).read_text().strip()) > 0, "Unprivileged user namespaces must be enabled for rootless Docker")
        restriction = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")
        if restriction.exists() and restriction.read_text().strip() == "1":
            profiles = Path("/sys/kernel/security/apparmor/profiles").read_text()[:MAX_OUTPUT]
            require(any((("rootlesskit" in profile or "dockerd-rootless" in profile) and "(enforce)" in profile) or profile == "rootlesskit (unconfined)" for profile in profiles.splitlines()), "Install and load the packaged rootlesskit AppArmor user-namespace profile")
        no_symlinks(self.storage)
        return self.subordinate_ranges()

    def systemctl(self, arguments, offline=False):
        environment = ["SYSTEMD_OFFLINE=1"] if offline else []
        return run_command(self.user_command([*environment, "/usr/bin/systemctl", "--user", *arguments]), timeout=30)

    def prepare_storage(self):
        self.verify_runtime(self.runtime_uid, self.runtime_gid)

    def unit_contents(self):
        runtime = "/run/user/" + str(self.runtime_uid)
        config = str(UNIT_DIR / (self.unit + ".json"))
        environment = "HOME=" + str(self.runtime_home) + " USER=" + self.runtime_user + " LOGNAME=" + self.runtime_user + " PATH=/usr/sbin:/usr/bin:/sbin:/bin XDG_RUNTIME_DIR=" + runtime + " DBUS_SESSION_BUS_ADDRESS=unix:path=" + runtime + "/bus DOCKERD_ROOTLESS_ROOTLESSKIT_STATE_DIR=" + runtime + "/aidipanel-rootlesskit"
        return ("[Unit]\nDescription=AidiPanel managed rootless Docker\nConditionUser=" + str(self.runtime_uid)
                + "\n[Service]\nType=exec\nDelegate=cpu memory pids\nRuntimeDirectory=aidipanel-docker aidipanel-rootlesskit\nRuntimeDirectoryMode=0700\nRestart=on-failure\nRestartSec=2\nTimeoutStartSec=60\nTimeoutStopSec=30\nKillMode=mixed\n"
                + "ExecStart=/usr/bin/env -i " + environment + " /usr/bin/dockerd-rootless.sh --config-file=" + config
                + " --host=unix://" + self.socket + " --data-root=" + str(self.storage / "data")
                + " --exec-root=" + runtime + "/aidipanel-docker --pidfile=" + runtime + "/aidipanel-docker/docker.pid"
                + "\n[Install]\nWantedBy=default.target\n")

    def enable(self):
        record = self.runtime_record()
        unit_path = UNIT_DIR / self.unit
        config_path = UNIT_DIR / (self.unit + ".json")
        if record is None:
            require(not os.path.lexists(unit_path) and not os.path.lexists(config_path)
                    and not os.path.lexists(self.runtime_home)
                    and not os.path.lexists("/run/user/" + str(self.uid) + "/docker.sock"),
                    "Unrecorded rootless resources cannot be adopted")
            try:
                pwd.getpwnam(self.runtime_user)
            except KeyError:
                pass
            else:
                raise ManagerError("Unrecorded runtime account cannot be adopted")
            try:
                grp.getgrnam(self.runtime_user)
            except KeyError:
                pass
            else:
                raise ManagerError("Unrecorded runtime group cannot be adopted")
            for source in (SUBUID, SUBGID):
                require(not any(line.partition(":")[0] == self.runtime_user for line in read_root_file(source).splitlines()),
                        "Unrecorded runtime subordinate-ID allocations cannot be adopted")
            self.prerequisites()
            if not RUNTIME_DIR.exists():
                secure_directory(RUNTIME_DIR, 0o711)
                os.chmod(RUNTIME_DIR, 0o711)
            else:
                secure_directory(RUNTIME_DIR, 0o711)
            require(stat.S_IMODE(RUNTIME_DIR.stat().st_mode) == 0o711, "Runtime parent must have mode 0711")
            run_command(["/usr/sbin/useradd", "--system", "--user-group", "--no-create-home", "--home-dir", str(self.runtime_home), "--shell", "/usr/sbin/nologin", self.runtime_user])
            account = pwd.getpwnam(self.runtime_user)
            self.runtime_home.mkdir(mode=0o700)
            os.chown(self.runtime_home, account.pw_uid, account.pw_gid)
            self.verify_runtime(account.pw_uid, account.pw_gid)
            record = {"version": 2, "domain": self.domain, "user": self.user, "home": str(self.home), "uid": self.uid, "unit": self.unit,
                      "runtime_user": self.runtime_user, "runtime_home": str(self.runtime_home), "runtime_uid": self.runtime_uid, "runtime_gid": self.runtime_gid}
            write_root_file(self.marker, json.dumps(record) + "\n")
            write_root_file(config_path, "{}\n", 0o644)
            write_root_file(unit_path, self.unit_contents(), 0o644)
        else:
            self.prerequisites()
            require(read_root_file(unit_path) == self.unit_contents() and read_root_file(config_path) == "{}\n", "Managed rootless service configuration has changed")
        self.prepare_storage()
        ranges = self.subordinate_ranges()
        for option, allocation in zip(("--add-subuids", "--add-subgids"), ranges):
            if allocation:
                run_command(["/usr/sbin/usermod", option, allocation, self.runtime_user])
        require(self.subordinate_ranges() == (None, None), "Required subordinate UID/GID allocations were not applied")
        try:
            run_command(["/usr/bin/loginctl", "enable-linger", self.runtime_user])
            run_command(["/usr/bin/systemctl", "start", "user@" + str(self.runtime_uid) + ".service"], timeout=30)
            self.systemctl(["daemon-reload"])
            self.systemctl(["enable", "--now", self.unit])
            deadline = time.monotonic() + 20
            while True:
                try:
                    information = self.info()
                    break
                except ManagerError:
                    require(time.monotonic() < deadline, "Rootless Docker did not become ready; check its user service and namespace prerequisites")
                    time.sleep(0.2)
            self.resources_available(information, verify_delegation=False)
            self.verify_data_root(information)
        except ManagerError:
            try:
                self.systemctl(["disable", "--now", self.unit])
            finally:
                run_command(["/usr/bin/loginctl", "disable-linger", self.runtime_user])
                run_command(["/usr/bin/systemctl", "stop", "user@" + str(self.runtime_uid) + ".service"], timeout=30)
            raise
        return {"success": True}

    def purge_storage(self):
        no_symlinks(self.storage)
        if not self.storage.exists():
            return
        require(self.storage.is_dir(), "Invalid managed Docker storage")
        require(shutil.rmtree.avoids_symlink_attacks, "Safe descriptor-based data removal is unavailable")
        for mount in host_mounts():
            require(not (mount == self.storage or mount.is_relative_to(self.storage)), "Unmount managed Docker data before purging it")
        descriptor = open_directory(self.storage.parent)
        try:
            metadata = os.stat(self.storage.name, dir_fd=descriptor, follow_symlinks=False)
            require(stat.S_ISDIR(metadata.st_mode), "Managed storage changed before removal")
            if sys.version_info >= (3, 11):
                shutil.rmtree(self.storage.name, dir_fd=descriptor)
            else:
                shutil.rmtree("/proc/self/fd/" + str(descriptor) + "/" + self.storage.name)
        finally:
            os.close(descriptor)

    def disable(self, purge=False):
        record = self.runtime_record()
        if record is None:
            try:
                pwd.getpwnam(self.runtime_user)
            except KeyError:
                pass
            else:
                raise ManagerError("Refusing teardown of an unrecorded runtime account")
            try:
                grp.getgrnam(self.runtime_user)
            except KeyError:
                pass
            else:
                raise ManagerError("Refusing teardown of an unrecorded runtime group")
            require(not os.path.lexists(self.runtime_home)
                    and not os.path.lexists("/run/user/" + str(self.uid) + "/docker.sock")
                    and not os.path.lexists(UNIT_DIR / self.unit)
                    and not os.path.lexists(UNIT_DIR / (self.unit + ".json")),
                    "Refusing teardown of an unrecorded Docker runtime; resolve its socket or service files manually")
            return {"success": True}
        if purge:
            no_symlinks(self.storage)
        try:
            information = self.info()
        except ManagerError:
            require(not self.socket_exists(), "Cannot verify the managed rootless daemon; resolve its socket before teardown")
        else:
            self.verify_data_root(information)
            containers = [self.inspect(identifier) for identifier in self.identifiers(managed_only=False)]
            require(all(self.managed(container) for container in containers), "Rootless daemon contains unmanaged containers; move them before disabling")
            for container in containers:
                if container.get("State", {}).get("Status") in ("running", "restarting", "paused"):
                    self.docker(["stop", "--time", "10", container["Id"]], timeout=20)
        state = run_command(["/usr/bin/systemctl", "show", "user@" + str(self.runtime_uid) + ".service", "--property=ActiveState", "--value"], timeout=30).strip()
        require(state in ("active", "activating", "reloading", "inactive", "failed"), "Cannot determine site user manager state")
        if state in ("active", "activating", "reloading"):
            self.systemctl(["disable", "--now", self.unit])
        else:
            self.systemctl(["--no-reload", "disable", self.unit], offline=True)
        run_command(["/usr/bin/loginctl", "disable-linger", self.runtime_user])
        run_command(["/usr/bin/systemctl", "stop", "user@" + str(self.runtime_uid) + ".service"], timeout=30)
        require(not self.socket_exists(), "Rootless socket still exists; runtime was not stopped")
        if purge:
            self.purge_storage()
            run_command(["/usr/sbin/userdel", self.runtime_user])
            for path in (UNIT_DIR / self.unit, UNIT_DIR / (self.unit + ".json"), self.marker):
                read_root_file(path)
                path.unlink()
        return {"success": True}

    def execute(self, action, payload, purge=False):
        require(action in ACTIONS and isinstance(payload, dict), "Invalid Docker action or JSON object")
        require(not purge or action == "disable" and self.scope == "site", "Purge requires site disable")
        if self.scope == "site":
            secure_directory(STATE_DIR)
            lock_path = STATE_DIR / "lock"
            descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                deadline = time.monotonic() + 5
                while True:
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        require(time.monotonic() < deadline, "Another rootless lifecycle operation is in progress")
                        time.sleep(0.05)
                return self._execute(action, payload, purge)
            finally:
                os.close(descriptor)
        return self._execute(action, payload, purge)

    def _execute(self, action, payload, purge):
        if action in ("enable", "disable"):
            require(self.scope == "site" and not payload, "Provisioning requires trusted site identity and no payload")
            return self.enable() if action == "enable" else self.disable(purge)
        if action in ("status", "list"):
            require(not payload, "Status and list do not accept payload fields")
        if self.scope == "site":
            record = self.runtime_record()
            if record is None and action in ("status", "list"):
                return {"available": os.access("/usr/bin/docker", os.X_OK), "enabled": False, "containers": []}
            require(record is not None, "Site Docker must be provisioned by an administrator")
        if action in ("status", "list"):
            try:
                information = self.info()
            except ManagerError:
                return {"available": self.scope == "site" and os.access("/usr/bin/docker", os.X_OK), "enabled": False, "containers": []}
            self.verify_data_root(information)
            containers = []
            for identifier in self.identifiers():
                container = self.inspect(identifier)
                if self.managed(container):
                    containers.append(self.summary(container))
            return {"available": True, "enabled": True, "containers": containers}
        if action == "create":
            arguments, input_data, limits = self.validate_create(payload)
            self.resources_available(self.verify_data_root(self.info()))
            if self.scope == "site":
                for volume in payload.get("volumes", []):
                    self.prepare_volume(volume["name"])
            identifier = self.docker(arguments, input_data=input_data, timeout=180).strip()
            require(re.fullmatch(r"[a-f0-9]{64}", identifier), "Docker did not return a valid created container ID")
            try:
                container = self.managed_container(identifier)
            except ManagerError:
                self.docker(["rm", "--volumes", identifier], timeout=15)
                raise
            if not all(container.get("HostConfig", {}).get(key) == value for key, value in limits.items()):
                self.docker(["rm", "--volumes", identifier], timeout=15)
                raise ManagerError("Docker did not apply the requested cgroup resource limits")
            return {"success": True, "id": identifier}
        require(set(payload) == {"id"}, "This operation requires only a managed container ID")
        require(isinstance(payload["id"], str) and ID_PATTERN.fullmatch(payload["id"]), "Invalid managed container ID")
        information = self.verify_data_root(self.info()) if self.scope == "site" else None
        container = self.managed_container(payload["id"])
        identifier = container["Id"]
        if action == "logs":
            output = self.docker(["logs", "--tail", "200", identifier], timeout=10, output_limit=MAX_OUTPUT, merge_output=True)
            return {"logs": redact(output, container.get("Config", {}).get("Env") or [], MAX_LOGS)}
        if action in ("start", "restart"):
            self.validate_existing_limits(container)
            self.resources_available(information if information is not None else self.info())
        commands = {"start": ["start"], "stop": ["stop", "--time", "10"], "restart": ["restart", "--time", "10"], "remove": ["rm"]}
        self.docker([*commands[action], identifier], timeout=25)
        return {"success": True}


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise ManagerError("Invalid Docker helper arguments")


def read_input():
    if sys.stdin.isatty():
        return ""
    try:
        descriptor = sys.stdin.fileno()
    except (AttributeError, OSError, ValueError):
        value = sys.stdin.read(MAX_INPUT + 1)
        require(len(value.encode("utf-8")) <= MAX_INPUT, "JSON input exceeds the size limit")
        return value
    result = bytearray()
    deadline = time.monotonic() + 5
    while True:
        remaining = deadline - time.monotonic()
        require(remaining > 0 and select.select([descriptor], [], [], remaining)[0], "JSON input timed out")
        chunk = os.read(descriptor, min(8192, MAX_INPUT + 1 - len(result)))
        if not chunk:
            break
        result.extend(chunk)
        require(len(result) <= MAX_INPUT, "JSON input exceeds the size limit")
    try:
        return result.decode("utf-8")
    except UnicodeDecodeError:
        raise ManagerError("JSON input must be UTF-8") from None


def main(arguments=None):
    try:
        parser = SafeParser(add_help=False, allow_abbrev=False)
        parser.add_argument("action", choices=ACTIONS)
        parser.add_argument("--scope", required=True, choices=("root", "site"))
        parser.add_argument("--domain")
        parser.add_argument("--user")
        parser.add_argument("--home")
        parser.add_argument("--purge", action="store_true")
        parsed = parser.parse_args(arguments)
        value = read_input()
        payload = checked_json(value) if value.strip() else {}
        manager = DockerManager(parsed.scope, parsed.domain, parsed.user, parsed.home)
        response = manager.execute(parsed.action, payload, parsed.purge)
        print(json.dumps(response, ensure_ascii=True, allow_nan=False))
        return 0
    except ManagerError as error:
        print(json.dumps({"success": False, "error": str(error)}))
        return 1
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
        print(json.dumps({"success": False, "error": "Docker operation failed; check identity, permissions and rootless prerequisites"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
