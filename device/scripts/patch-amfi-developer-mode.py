#!/usr/bin/env python3
"""Force AMFI's developer-mode resolution onto its PMGR-free path.

AMFI's ConfigurationSettings resolves developer mode by matching the original
ApplePMGRNub service and reading a PMGR AON register through it; this board has
neither the PMGR hardware nor that nub, so AMFI panics with "AMFI: No PMGR?".
The same routine has a PMGR-free branch ("AMFI: developer mode is force
enabled") selected by one static byte. Clearing that byte in the prelinked AMFI
data makes the routine take the PMGR-free branch at start.

The byte is located by decoding AMFI's own code, never by a fixed address:

    adrp xN, <data page>
    add  xN, xN, #imm              ; address of the settings structure
    ldrb wM, [xN, #7]              ; the developer-mode flag
    cbz  wM, <PMGR-free branch>

Only initialized data changes; no executable byte is touched, which keeps the
prelink invariant "original executable bytes unchanged". A tiny ARM64 decoder
is used instead of a disassembler dependency.
"""
import argparse
import plistlib
import struct
from pathlib import Path

AMFI_BUNDLE = 'com.apple.driver.AppleMobileFileIntegrity'


def segments(data, base=0):
    magic, _, _, _, ncmds, _, _, _ = struct.unpack_from('<IiiIIIII', data, base)
    if magic != 0xFEEDFACF:
        raise ValueError(f'not a 64-bit Mach-O at {base:#x}')
    offset, out, info = base + 32, [], None
    for _ in range(ncmds):
        command, length = struct.unpack_from('<II', data, offset)
        if command == 0x19:
            name = data[offset + 8:offset + 24].split(b'\0')[0].decode()
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from('<QQQQ', data, offset + 24)
            out.append((name, vmaddr, vmsize, fileoff, filesize))
            nsects = struct.unpack_from('<I', data, offset + 64)[0]
            addr = offset + 72
            for _ in range(nsects):
                section = data[addr:addr + 16].split(b'\0')[0]
                size, soff = struct.unpack_from('<QI', data, addr + 40)
                if section == b'__info':
                    info = (size, soff)
                addr += 80
        offset += length
    return out, info


def kexts(image):
    for name, vmaddr, vmsize, fileoff, filesize in segments(image)[0]:
        if name == '__PRELINK_INFO':
            blob = image[fileoff:fileoff + filesize]
            first, last = blob.find(b'<dict>'), blob.rfind(b'</dict>')
            return plistlib.loads(b'<plist version="1.0">' + blob[first:last + 7] + b'</plist>')
    raise ValueError('no __PRELINK_INFO segment')


def file_offset(image, va):
    for name, vmaddr, vmsize, fileoff, filesize in segments(image)[0]:
        if vmaddr <= va < vmaddr + filesize:
            return fileoff + va - vmaddr
    raise ValueError(f'{va:#x} is not backed by the image')


def sign_extend(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def find_flag(image):
    entry = next(e for e in kexts(image)['_PrelinkInfoDictionary']
                 if e.get('CFBundleIdentifier') == AMFI_BUNDLE)
    amfi_base = file_offset(image, entry['_PrelinkExecutableLoadAddr'])
    amfi_segments, _ = segments(image, amfi_base)
    name, vmaddr, vmsize, fileoff, filesize = next(s for s in amfi_segments if s[0] == '__TEXT_EXEC')
    # A kext's segment file offsets are relative to its own header, which sits
    # inside the coalesced prelink segment of the image.
    blob = image[amfi_base + fileoff:amfi_base + fileoff + filesize]
    words = struct.unpack_from(f'<{len(blob) // 4}I', blob)

    def adrp(word, pc):
        imm = (((word >> 5) & 0x7ffff) << 2) | ((word >> 29) & 3)
        return (pc & ~0xfff) + (sign_extend(imm, 21) << 12)

    values = {}
    found = []
    for index, word in enumerate(words):
        pc = vmaddr + index * 4
        if word & 0x9f000000 == 0x90000000:                       # ADRP
            values[word & 31] = adrp(word, pc)
            continue
        if word & 0x7f000000 == 0x11000000 and word >> 31:        # ADD (immediate), 64-bit
            rn, rd = (word >> 5) & 31, word & 31
            imm = (word >> 10) & 0xfff
            if (word >> 22) & 3:
                imm <<= 12
            if rn in values:
                values[rd] = (values[rn] + imm) & 0xffffffffffffffff
            continue
        if word & 0xffc00000 != 0x39400000:                       # LDRB (unsigned offset)
            continue
        if (word >> 10) & 0xfff != 7:
            continue
        rn, rt = (word >> 5) & 31, word & 31
        if rn not in values or index + 1 >= len(words):
            continue
        following = words[index + 1]
        if following & 0x7e000000 != 0x34000000:                  # CBZ/CBNZ (32-bit)
            continue
        if following & 31 != rt:
            continue
        found.append(((values[rn] + 7) & 0xffffffffffffffff, pc, vmaddr + (index + 1) * 4))
    if len(found) != 1:
        raise SystemExit(f'expected one developer-mode flag test in AMFI, found {len(found)}')
    return found[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--kernel', required=True, type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    image = bytearray(args.kernel.read_bytes())
    original = bytes(image)
    flag, ldrb, branch = find_flag(image)
    offset = file_offset(image, flag)
    before = image[offset]
    print(f'developer-mode flag {flag:#x} (test at {ldrb:#x}, branch at {branch:#x}) = {before:#x}')
    if before == 0:
        print('already on the PMGR-free branch')
        return 0
    if args.dry_run:
        return 0
    image[offset] = 0
    args.kernel.write_bytes(image)

    # Exactly this one data byte may differ; size and every other byte stay put.
    check = args.kernel.read_bytes()
    if len(check) != len(original):
        raise SystemExit('image size changed')
    if check[:offset] != original[:offset] or check[offset + 1:] != original[offset + 1:]:
        raise SystemExit('bytes other than the developer-mode flag changed')
    print(f'{args.kernel}: AMFI developer-mode flag cleared ({before:#x} -> 0), code untouched')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
