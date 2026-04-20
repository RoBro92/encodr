# Storage Setup

Encodr expects your media library at:

```text
/media
```

This is the standard in-container media root used by the app, the installer guidance, the worker, and the storage health UI.

Encodr also expects its transcode scratch workspace at:

```text
/temp
```

The installer and bootstrap flow create both `/media` and `/temp` automatically. That keeps first start simple, but Encodr now warns if those paths look empty or appear to share the container root filesystem instead of a real mounted library or scratch disk.

## Recommended Proxmox LXC model

Recommended order:

1. mount the NFS or SMB share on the Proxmox host
2. pass it into the LXC as a mount point
3. let Docker inside the LXC expose that same path to Encodr at `/media`
4. mount your fast local or NVMe scratch storage into the LXC at `/temp`

This keeps network storage on the host side and makes container diagnostics simpler.

## Linux VM or direct host model

If you are running Encodr directly in a Linux VM or on a Linux host, mount the share with `/etc/fstab` so it is available at `/media`, mount your scratch storage at `/temp`, then start the stack.

## Validation

Use:

```bash
encodr mount-setup --validate-only
```

Encodr will report whether `/media`:

- exists
- is readable
- is writable
- looks empty when you expected a library mount
- appears to share the container root filesystem when you expected a real mount

Encodr will also report whether `/temp`:

- exists
- is writable
- appears to be on a dedicated scratch mount

The System page in the web UI also shows the same storage diagnostics.

Typical messages are:

- `Media mount not found at /media`
- `Media path is empty. If you expected a mounted library, check the host or LXC bind mount.`
- `Media path exists but is not readable`
- `Media path exists but is not writable`
- `Scratch path is available but does not appear to be on a dedicated /temp mount.`
- `Storage is not configured yet`

## Guidance output

You can ask Encodr for host-side guidance:

```bash
encodr mount-setup --type nfs --host-source 10.0.0.10:/share
encodr mount-setup --type smb --host-source //server/share
```

This prints suggested host-side mount snippets and the recommended LXC-visible target path.

## Notes

- scratch space should stay on fast local storage such as NVMe, not on the media share
- Encodr can start before storage is mounted, but jobs should wait until `/media` is healthy
- Encodr can create `/temp` automatically, but you should still mount a dedicated scratch disk there for real transcode workloads
- if you want verified files to be written back into the library, `/media` must be writable
