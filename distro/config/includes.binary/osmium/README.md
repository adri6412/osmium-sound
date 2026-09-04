# System image for the installer

The ISO build drops `rootfs.squashfs` (and its `.sha256`) here, and live-build
copies this directory to the root of the ISO. `hifi-disk-install.sh` looks for
`<medium>/osmium/rootfs.squashfs` and, when it is there and the machine boots
UEFI, installs the A/B layout: five partitions, the image written block for
block into slot A, `/data` formatted and seeded, boot selector and grubenv on
the ESP. Nothing is downloaded during the installation.

Without this file the installer falls back to the historical single-root
install, so an ISO built without the image still works — it just produces a
legacy system that has to convert itself later over the network.
