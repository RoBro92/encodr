# Storage Setup

## Recommended model

For Proxmox and Debian LXC, the preferred storage model is:

1. mount the NFS or SMB share on the Proxmox host
2. bind-mount that host path into the LXC
3. bind the LXC-visible path into Docker inside the LXC

This keeps network filesystem concerns on the host and makes the container-side runtime simpler and easier to diagnose.

## Operator helper

Use:

```bash
encodr mount-setup --validate-only
```

Optional guidance mode:

```bash
encodr mount-setup --type nfs --host-source 10.0.0.10:/media
```

The command can:
- validate the container-visible path
- report readability and writability
- create the target directory if asked
- print a suggested `/etc/fstab` line
- print a suggested Proxmox `mp0` style mount-point snippet

## Path expectations

- media shares should be mounted separately from scratch
- scratch should live on fast local storage where possible
- mounted media paths must be readable and writable from the LXC if Encodr is expected to replace files

## Fallback

In-container NFS or SMB mounts are possible, but they are a secondary option and come with more operational caveats. The host-bind-mount model remains the recommended approach.
