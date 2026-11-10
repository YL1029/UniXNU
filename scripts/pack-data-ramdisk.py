#!/usr/bin/env python3
"""Pack a raw APFS disk image into the DBRDISK1 sparse RAM-disk format.

    pack-data-ramdisk.py INPUT.img OUTPUT.img [--page 4096] [--max-inflate 256MiB]

DarwinBoot (PackedRamdisk.h) and NativeRamBlock (SparseDisk.h) read the same
layout: the 8-byte tag, version 1, the page size, the logical size, the extent
count, a sorted table of (destination offset, byte count) pairs, and the
concatenated nonzero runs. Omitted ranges are real zeros in RAM, so a sparse
APFS container packs down to its metadata plus real files.

The packed result must stay below 256 MiB: DarwinBoot refuses a larger initrd.
"""
import struct
import sys
from pathlib import Path

PAGE = 4096
MAX_PACKED = 256 * 1024 * 1024
MAX_EXTENTS = 65536


def main():
    args = [item for item in sys.argv[1:] if not item.startswith('--')]
    image = Path(args[0])
    output = Path(args[1])
    if image.stat().st_size % PAGE:
        raise SystemExit(f'{image}: size is not a multiple of {PAGE}')
    logical = image.stat().st_size
    extents = []
    data = bytearray()
    with image.open('rb') as handle:
        offset = 0
        run_start = None
        while offset < logical:
            page = handle.read(PAGE)
            if len(page) != PAGE:
                raise SystemExit(f'{image}: short read at {offset}')
            nonzero = page.count(0) != PAGE
            if nonzero and run_start is None:
                run_start = offset
            elif not nonzero and run_start is not None:
                extents.append((run_start, offset - run_start))
                run_start = None
            offset += PAGE
        if run_start is not None:
            extents.append((run_start, logical - run_start))
    if len(extents) > MAX_EXTENTS:
        raise SystemExit(f'{image}: {len(extents)} extents exceed the {MAX_EXTENTS} the loader accepts')
    with image.open('rb') as handle:
        for start, length in extents:
            handle.seek(start)
            data += handle.read(length)
    header = struct.pack('<8sIIQQ', b'DBRDISK1', 1, PAGE, logical, len(extents))
    table = b''.join(struct.pack('<QQ', start, length) for start, length in extents)
    packed = header + table + bytes(data)
    if len(packed) > MAX_PACKED:
        raise SystemExit(f'{output}: packed size {len(packed) >> 20} MiB exceeds the 256 MiB initrd limit')
    output.write_bytes(packed)
    nonzero = sum(length for _, length in extents)
    print(f'{output}: {len(packed)} bytes ({nonzero >> 20} MiB of {logical >> 20} MiB, '
          f'{len(extents)} extents)')


if __name__ == '__main__':
    main()
