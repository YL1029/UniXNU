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
            # Map each input check to a distinct error code and log so we can pinpoint failure exactly
            old_check = (
                '  if ((Request->KextCount != 0) || (Request->DeviceTree != NULL) || (Request->DeviceTreeSize != 0) ||\n'
                '      (DarwinCurrentEl () != 4)) {\n'
                '    Print (L"DARWINBOOT: unsupported inputs or exception level; firmware retained\\n");\n'
                '    return EFI_UNSUPPORTED;\n'
                '  }'
            )
            new_check = (
                '  UINT64 CurrentEl = DarwinCurrentEl ();\n'
                '  if (Request->KextCount != 0) {\n'
                '    Print (L"DARWINBOOT: KextCount != 0 (%u)\\n", (UINT32)Request->KextCount);\n'
                '    return EFI_ACCESS_DENIED;\n'
                '  }\n'
                '  if (Request->DeviceTree != NULL || Request->DeviceTreeSize != 0) {\n'
                '    Print (L"DARWINBOOT: DeviceTree non-null (size %u)\\n", (UINT32)Request->DeviceTreeSize);\n'
                '    return EFI_MEDIA_CHANGED;\n'
                '  }\n'
                '  if ((CurrentEl != 4) && (CurrentEl != 8)) {\n'
                '    Print (L"DARWINBOOT: Unsupported EL: %llu\\n", CurrentEl);\n'
                '    return EFI_BAD_BUFFER_SIZE;\n'
                '  }'
            )
            if old_check in c:
                c = c.replace(old_check, new_check)
            else:
                c = re.sub(
                    r'if \(\(Request->KextCount != 0\).*?\(DarwinCurrentEl \(\) != 4\)\) \{.*?return EFI_UNSUPPORTED;\s*\}',
                    new_check,
                    c, flags=re.DOTALL
                )

            # In Fail block, wait 5 seconds if DiagDraw fails so the user can read it if GOP is working, or keep error
            old_fail = 'Fail:\n  if (Root != NULL)'
            new_fail = (
                'Fail:\n'
                '  if (EFI_ERROR (Status)) {\n'
                '    CHAR16 ErrBuf[96];\n'
                '    UnicodeSPrint (ErrBuf, sizeof (ErrBuf), L"DARWINBOOT FAIL: %r", Status);\n'
                '    DiagDraw (ErrBuf, 0);\n'
                '  }\n'
                '  if (Root != NULL)'
            )
            c = c.replace(old_fail, new_fail)

            # If BootVideo fails in ReadBootVideo, return specific error
            old_bv_call = 'Status = ReadBootVideo (Video);\n  if (EFI_ERROR (Status)) { goto Fail; }'
            new_bv_call = 'Status = ReadBootVideo (Video);\n  if (EFI_ERROR (Status)) { Print (L"DARWINBOOT: ReadBootVideo fail: %r\\n", Status); Status = EFI_NO_RESPONSE; goto Fail; }'
            c = c.replace(old_bv_call, new_bv_call)

            # If ParseKernel fails
            old_pk_call = 'Status = ParseKernel (Image, ImageSize, &Kernel);\n  if (EFI_ERROR (Status)) { goto Fail; }'
            new_pk_call = 'Status = ParseKernel (Image, ImageSize, &Kernel);\n  if (EFI_ERROR (Status)) { Print (L"DARWINBOOT: ParseKernel fail: %r\\n", Status); Status = EFI_NOT_FOUND; goto Fail; }'
            c = c.replace(old_pk_call, new_pk_call)

            # If ReadFile TreePath fails (.adt)
            old_rf_adt = 'Status = ReadFile (Root, TreePath, SIZE_16MB, &Tree, &TreeSize);\n  if (EFI_ERROR (Status)) { goto Fail; }'
            new_rf_adt = 'Status = ReadFile (Root, TreePath, SIZE_16MB, &Tree, &TreeSize);\n  if (EFI_ERROR (Status)) { Print (L"DARWINBOOT: ReadFile .adt fail: %r\\n", Status); Status = EFI_NOT_READY; goto Fail; }'
            c = c.replace(old_rf_adt, new_rf_adt)

            db.write_text(c, encoding='utf-8', newline='\n')
            print("  [+] Patched DarwinBoot.c (instrumented checks & distinct error codes)")

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
