# Hardware and protocol

Verified original setup: TURMO 3.5-inch USB secondary display, `1a86:5722`,
`USB35INCHIPSV2`, appearing as a Linux CDC-ACM serial port. The enclosure label
alone is not sufficient to identify another unit's hardware revision.

The application uses the Turing Revision A host protocol: 115200 baud, RTS/CTS,
six-byte `45` handshake and `01` response, followed by coordinate-packed commands
and RGB565 little-endian pixels. This is a vendor-derived protocol implementation,
not an open-standard or USB video-class conformance claim.

Native portrait dimensions are 320 x 480. Wire orientation values are 100 for
portrait and 101 for reverse portrait; landscape is 102, not 101. A landscape
frame sent while in portrait mode produces wrapped/overlapping pixels. Keep
dimensions and orientation consistent. The tested cable-at-top arrangement uses
reverse portrait. Change `reverse_portrait` if your enclosure is mounted differently.

The public application currently renders portrait pages only. It does not flash
firmware, reset the USB device, use touch input or provide a normal desktop monitor.
The tested unit exposes serial communications/data interfaces, not a USB HID
touch interface. This does not establish the capabilities of other models.

Automatic detection requires one matching USB identity. With multiple displays,
set `serial_port` to the intended stable `/dev/serial/by-id/...` path. Unexpected
handshake replies stop before display commands are sent.
