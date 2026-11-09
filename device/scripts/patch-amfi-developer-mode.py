#!/usr/bin/env python3
"""Force AMFI's developer-mode resolution onto its PMGR-free path.

AMFI's ConfigurationSettings resolves developer mode by matching the original
ApplePMGRNub service and reading a PMGR AON register through it; on this board
there is no PMGR hardware and no nub, so it panics with "AMFI: No PMGR?".
The same routine already has a PMGR-free branch ("developer mode is force
enabled") selected by one static byte. This tool clears that byte in the
prelinked AMFI data, so the routine takes the PMGR-free branch at start.

The byte is located by decoding AMFI's own code (ldrb + cbz after an ADRP/ADD
pair), never by a fixed address, so a different kernelcache layout still works.
Only initialized data changes; no executable byte is touched, matching the
prelink invariant.
"""
import argparse
import struct
from pathlib import Path

import capstone

PRELINK_SECTION = b'__info'
AMFI_BUNDLE = 'com.apple.driver.AppleMobileFileIntegrity'


def segments(data, base=0):
    magic, _, _, _, ncmds, _, _, _ = struct.unpack_from('<IiiIIIII', data, base)
    if magic != 0xFEEDFACF:
        raise ValueError(f'not a 64-bit Mach-O at {base:#x}')
    offset = base + 32
    out, info = [], None
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
                if section == PRELINK_SECTION:
                    info = (size, soff)
                addr += 80
        offset += length
    return out, info


def load_section(image):
    """(file offset, size) of __PRELINK_INFO,__info in the image."""
    for name, vmaddr, vmsize, fileoff, filesize in segments(image)[0]:
        if name == '__PRELINK_INFO':
            return fileoff, filesize
    raise ValueError('no __PRELINK_INFO segment')


def kext_entries(image):
    import plistlib
    start, size = load_section(image)
    blob = image[start:start + size]
    first = blob.find(b'<dict>')
    last = blob.rfind(b'</dict>')
    return plistlib.loads(b'<plist version="1.0">' + blob[first:last + 7] + b'</plist>')


def file_offset(image, va):
    for name, vmaddr, vmsize, fileoff, filesize in segments(image)[0]:
        if vmaddr <= va < vmaddr + filesize:
            return fileoff + va - vmaddr
    raise ValueError(f'{va:#x} is not backed by the image')


def find_flag(image):
    entry = next(e for e in kext_entries(image)['_PrelinkInfoDictionary']
                 if e.get('CFBundleIdentifier') == AMFI_BUNDLE)
    load = entry['_PrelinkExecutableLoadAddr']
    amfi_base = file_offset(image, load)
    amfi_segments, _ = segments(image, amfi_base)
    text = next(s for s in amfi_segments if s[0] == '__TEXT_EXEC')

    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    md.detail = True
    found = []
    for name, vmaddr, vmsize, fileoff, filesize in [text]:
        # A kext's own segment file offsets are relative to its header, which
        # lives inside the coalesced prelink segment of the image.
        blob = image[amfi_base + fileoff:amfi_base + fileoff + filesize]
        recent = {}
        instructions = list(md.disasm(blob, vmaddr))
        for index, insn in enumerate(instructions[:-1]):
            if insn.mnemonic == 'adrp':
                recent[insn.operands[0].reg] = insn.operands[1].imm & 0xffffffffffffffff
                continue
            if insn.mnemonic in ('add', 'sub') and len(insn.operands) == 3:
                dst, src, imm = insn.operands
                if src.type == capstone.arm64.ARM64_OP_REG and \
                        imm.type == capstone.arm64.ARM64_OP_IMM and src.reg in recent:
                    delta = imm.imm if insn.mnemonic == 'add' else -imm.imm
                    recent[dst.reg] = (recent[src.reg] + delta) & 0xffffffffffffffff
                continue
            if insn.mnemonic != 'ldrb' or len(insn.operands) != 2:
                continue
            ops = insn.operands
            if ops[1].type != capstone.arm64.ARM64_OP_MEM or ops[1].mem.disp != 7:
                continue
            following = instructions[index + 1]
            if following.mnemonic not in ('cbz', 'cbnz'):
                continue
            base_va = recent.get(ops[1].mem.base)
            if base_va is None:
                continue
            found.append(((base_va + 7) & 0xffffffffffffffff, insn.address, following.address))
    if len(found) != 1:
        raise SystemExit(f'expected one developer-mode flag test in AMFI, found {len(found)}: '
                         f'{[(hex(a), hex(b)) for a, b, _ in found]}')
    return found[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--kernel', required=True, type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    image = bytearray(args.kernel.read_bytes())
    original = bytes(image)
    flag, ldrb, cbz = find_flag(image)
    offset = file_offset(image, flag)
    before = image[offset]
    print(f'developer-mode flag {flag:#x} (test at {ldrb:#x}, branch at {cbz:#x}) = {before:#x}')
    if before == 0:
        print('already on the PMGR-free branch')
        return 0
    if args.dry_run:
        return 0
    image[offset] = 0
    args.kernel.write_bytes(image)

    # Exactly this one data byte may differ; every executable segment and the
    # image size stay identical.
    check = args.kernel.read_bytes()
    if len(check) != len(original):
        raise SystemExit('image size changed')
    if check[:offset] != original[:offset] or check[offset + 1:] != original[offset + 1:]:
        raise SystemExit('bytes other than the developer-mode flag changed')
    print(f'{args.kernel}: AMFI developer-mode flag cleared ({before:#x} -> 0), code untouched')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
