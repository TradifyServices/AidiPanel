# Disposable Ubuntu 24.04 integration run

Date: 2026-11-10. Guest: Ubuntu 24.04.5 LTS, x86-64, kernel
6.8.0-147-generic; QEMU/KVM, one vCPU, 1024 MiB RAM, 30 GiB virtual disk.
Only one guest ran at a time. Networking used QEMU user NAT and an SSH forward
bound to host loopback. Guest package, service, firewall and user changes were
confined to the VM.

The official `noble-server-cloudimg-amd64.img` matched Canonical's SHA256SUMS;
its detached signature verified with the UEC Image Automatic Signing Key
`D2EB44626FDDC30B513D5BB71A5D6C4C7DB87C81` obtained from Ubuntu's keyserver.
The key was not certified by a local GPG trust chain. A first boot was stopped
before installation while verification was completed; all installs used fresh
overlays based on the verified image.

The current uncommitted CLI and panel files were staged beside `install.sh`,
using its local-source deployment path. This does not exercise the public signed
release download path. No production signing key or integrity check was changed.
The Valkey run initially required `apt-get update` because the pristine cloud
image had no current package candidates. Its first retry exposed an `apt-cache`
SIGPIPE under `pipefail`; the candidate parser was fixed and tested before the
successful fresh install. An interruption stopped one intermediate installation;
that incomplete disk was retained separately and was not counted as a pass.

## Valkey and Docker profile

Command: `sudo bash install.sh --plain --cache-engine valkey --with-docker`
after refreshing the guest's signed Ubuntu package indexes. Installer exited 0.
Valkey, Docker, MariaDB, Nginx, PHP-FPM and the panel FPM service were active.
The installed helper was updated inside the guest after the two rootless fixes
described below; subsequent integration results include those fixes.

- **PASS:** Valkey rejects unauthenticated requests. Two WordPress sites enabled
  object caching; ACL status reported two isolated sites with no drift. A site
  credential wrote its own prefix and was denied reads and writes to the other.
- **PASS:** Rootful managed Nginx create, start, bounded logs, stop and remove;
  published address was `127.0.0.1`. A separately created unrelated container
  survived operations and site teardown.
- **PASS:** A PHP site received a separate no-login `apdock_SITEUID` runtime;
  its original site account could not traverse the private home or access the
  Docker socket. Rootless Nginx served HTTP on a loopback-only published port.
- **PASS:** Live cgroup v2 limits were CPU `50000 100000`, memory `100663296`
  bytes and 64 PIDs. CPU throttling and PID limit events increased, and a memory
  allocation exceeded the limit and produced an OOM kill event.
- **PASS:** The rootless service and container record returned after a guest
  reboot. Named-volume content survived reboot, normal disable/reenable, an
  offline user-manager disable/reenable, and container removal/recreation.
- **PASS:** An image declaring `/data` as a volume was rejected and rolled back
  without a mapping, and succeeded with an explicit managed named volume.
  Rootless creation also succeeded with a nonempty environment passed via stdin.
- **PASS:** Keep-home site deletion stopped the runtime and retained home and
  runtime data. A separate `--purge --yes --user` deletion removed both site and
  runtime identities and homes without affecting the unrelated container.
- **PASS:** Holding the site's security lock caused both Docker list and site
  deletion to return busy, leaving the site intact. This is a targeted lock
  contention check, not an exhaustive concurrent lifecycle stress test.

Ubuntu's packaged `rootlesskit` AppArmor profile is loaded as `unconfined` and
explicitly grants `userns`; a real rootlesskit namespace worked, but the helper
previously rejected that profile. The helper now recognizes that exact packaged
profile. A second failure occurred because a root-owned environment stdin pipe
could not be reopened by the separate runtime UID. The pipe is now owned by that
UID before the child starts; a real cross-UID reopen regression was run as root
inside the guest, and live Docker creation was repeated successfully.

## Local regression checks

`bash tests/unit/installer_components_test.sh` reproduced exit 141 before the
parser fix and passed afterward. The AppArmor profile regression failed before
its fix and passed afterward. The cross-UID stdin test failed before its fix
and passed as root in the guest. Final local checks: 44 shell contracts passed;
Python discovery ran 75 tests successfully with the root-only stdin test skipped
on the unprivileged host; `bash -n install.sh` and `git diff --check` passed.

## Redis and Docker opt-out profile

On a separate pristine overlay, `sudo bash install.sh --plain --cache-engine
redis --no-docker` exited 0 after an index refresh. Redis, MariaDB, Nginx,
PHP-FPM and panel FPM were active; unauthenticated Redis returned NOAUTH, ACL
status showed default locked and an admin account, Docker Engine and its CLI
were absent, and `docker:status` reported unavailable and disabled. No Redis
site or reboot integration was run on this profile. Cache `none`, other OSes,
the public release download/signature flow and production deployment are untested.

## Retained artifacts

The VM was shut down cleanly. Its private run directory is
`/home/tfsbs/aidipanel-vm-20261110-AVozli/`: `guest-fresh.qcow2` is the
Valkey/Docker run, `guest-redis.qcow2` is the Redis/opt-out run, and
`guest-verified.qcow2` is the interrupted installation. The verified base image,
seed, source snapshots, QEMU logs and SSH key are in the same directory. These
disks and guest logs contain disposable credentials and must remain private; one
test-only generated credential was inadvertently displayed in tool output and
must not be reused. The displayed value was the initial panel `admin` password
on the Valkey/Docker guest. It was verified against that account, replaced with
a securely generated password inside the guest, and verified to be rejected
afterward. The replacement was discarded, so that guest's panel admin password
will need to be reset again if panel login is needed. The stale admin-password
entry was removed from the guest credentials file. Existing authenticated session
hashes were invalidated by the password change, and panel-owned session files
were removed to invalidate sessions awaiting two-factor authentication. The same
exposed password was verified not to authenticate the admin account on the Redis
or interrupted-install disks. This mitigation does not erase the earlier output
or historical guest logs. All three profiles were shut down after the checks.

To reboot one profile, run `./boot-valkey.sh` or `./boot-redis.sh` from that
directory; run only one at a time. SSH is forwarded on `127.0.0.1:41035`; use
`ssh -i id_ed25519 -p 41035 -o UserKnownHostsFile=known_hosts vmtest@127.0.0.1`.
The profiles have different host keys: remove the old entry from that private
known-hosts file and verify the guest host fingerprint before switching profiles.
