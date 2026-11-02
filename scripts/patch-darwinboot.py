#!/usr/bin/env python3
import sys
from pathlib import Path
import re

def patch_darwinboot(darwinboot_dir):
    d = Path(darwinboot_dir) / 'DarwinBootPkg/Driver'
    if not d.is_dir():
        print(f"Warning: {d} not found")
        return False

    # 1. Patch BootVideo.h
    bv = d / 'BootVideo.h'
    if bv.is_file():
        c = bv.read_text(encoding='utf-8')
        if 'PixelRedGreenBlueReserved8BitPerColor' not in c:
            c = c.replace(
                'if (Info->PixelFormat != PixelBlueGreenRedReserved8BitPerColor) { return EFI_UNSUPPORTED; }',
                'if ((Info->PixelFormat != PixelBlueGreenRedReserved8BitPerColor) && (Info->PixelFormat != PixelRedGreenBlueReserved8BitPerColor) && (Info->PixelFormat != PixelBitMask)) { return EFI_UNSUPPORTED; }'
            )
            bv.write_text(c, encoding='utf-8', newline='\n')
            print("  [+] Patched BootVideo.h (added RGB & BitMask GOP support)")

    # 2. Patch DarwinBoot.c
    db = d / 'DarwinBoot.c'
    if db.is_file():
        c = db.read_text(encoding='utf-8')
        if 'CurrentEl != 8' not in c:
            c = re.sub(
                r'if \(\(Request->KextCount != 0\).*?\(DarwinCurrentEl \(\) != 4\)\) \{',
                'UINT64 CurrentEl = DarwinCurrentEl ();\n  if ((Request->KextCount != 0) || (Request->DeviceTree != NULL) || (Request->DeviceTreeSize != 0) || ((CurrentEl != 4) && (CurrentEl != 8))) {',
                c, flags=re.DOTALL
            )
            c = c.replace(
                'Fail:\n  if (Root != NULL)',
                'Fail:\n  if (EFI_ERROR (Status)) { CHAR16 ErrBuf[96]; UnicodeSPrint (ErrBuf, sizeof (ErrBuf), L"FAIL: %r", Status); DiagDraw (ErrBuf, 0); }\n  if (Root != NULL)'
            )
            db.write_text(c, encoding='utf-8', newline='\n')
            print("  [+] Patched DarwinBoot.c (added EL2/EL1 check & DiagDraw fail)")

    # 3. Patch Entry.S
    es = d / 'Entry.S'
    if es.is_file():
        c = es.read_text(encoding='utf-8')
        if 'mrs x7, CurrentEL' not in c:
            target = '  tlbi vmalle1\n  dsb sy\n  isb\n  br x1'
            replacement = '  tlbi vmalle1\n  dsb sy\n  isb\n  mrs x7, CurrentEL\n  cmp x7, #8\n  b.ne 4f\n  mov x8, #(1 << 31)\n  msr hcr_el2, x8\n  mov x8, #0x3c5\n  msr spsr_el2, x8\n  msr elr_el2, x1\n  eret\n4:\n  br x1'
            c = c.replace(target, replacement)
            es.write_text(c, encoding='utf-8', newline='\n')
            print("  [+] Patched Entry.S (added EL2->EL1 drop)")
    return True

if __name__ == '__main__':
    target_dir = sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / 'drivers/DarwinBoot'
    patch_darwinboot(target_dir)
