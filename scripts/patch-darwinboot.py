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
        if 'BltOnly' not in c:
            new_bv = '''// SPDX-License-Identifier: BSD-2-Clause-Patent
#ifndef DARWIN_BOOT_VIDEO_H_
#define DARWIN_BOOT_VIDEO_H_

#include <Uefi.h>
#include <Library/BaseMemoryLib.h>
#include <Library/PrintLib.h>
#include <Library/UefiLib.h>
#include <Protocol/GraphicsOutput.h>

STATIC
EFI_STATUS
DarwinBootVideoFromGop (CONST EFI_GRAPHICS_OUTPUT_PROTOCOL *Gop, UINT64 Video[6])
{
  EFI_GRAPHICS_OUTPUT_MODE_INFORMATION *Info;
  UINT64 RowBytes;
  UINT64 Bytes;

  ZeroMem (Video, 6 * sizeof (*Video));
  if ((Gop == NULL) || (Gop->Mode == NULL) || (Gop->Mode->Info == NULL) ||
      (Gop->Mode->SizeOfInfo < sizeof (*Info))) {
    Print (L"DARWINBOOT: GOP or Info is NULL\\n");
    return EFI_SUCCESS;
  }
  Info = Gop->Mode->Info;
  Print (L"DARWINBOOT: GOP mode %u: %ux%u format=%u scanline=%u fb=0x%lx size=0x%lx\\n",
         Gop->Mode->Mode, Info->HorizontalResolution, Info->VerticalResolution,
         Info->PixelFormat, Info->PixelsPerScanLine,
         Gop->Mode->FrameBufferBase, Gop->Mode->FrameBufferSize);

  // If BltOnly (PixelBltOnly=3) or no direct linear framebuffer, do not abort boot!
  // Fall back to headless/text mode so XNU kernel can boot and print to serial console.
  if ((Info->PixelFormat == PixelBltOnly) || (Gop->Mode->FrameBufferBase == 0)) {
    Print (L"DARWINBOOT: BltOnly or FB=0, fallback to headless video\\n");
    return EFI_SUCCESS;
  }

  RowBytes = (UINT64)Info->PixelsPerScanLine * 4;
  if ((Info->HorizontalResolution == 0) || (Info->VerticalResolution == 0) ||
      (Info->PixelsPerScanLine < Info->HorizontalResolution) ||
      (Info->VerticalResolution > MAX_UINT64 / RowBytes)) {
    Print (L"DARWINBOOT: Invalid GOP dimensions, fallback to headless\\n");
    return EFI_SUCCESS;
  }

  Bytes = RowBytes * Info->VerticalResolution;
  if ((Gop->Mode->FrameBufferBase & 3) ||
      (Gop->Mode->FrameBufferSize < Bytes) ||
      (Gop->Mode->FrameBufferBase > MAX_UINT64 - Gop->Mode->FrameBufferSize)) {
    Print (L"DARWINBOOT: GOP buffer size check mismatch, fallback to headless\\n");
    return EFI_SUCCESS;
  }

  Video[0] = Gop->Mode->FrameBufferBase;
  Video[1] = 1;
  Video[2] = RowBytes;
  Video[3] = Info->HorizontalResolution;
  Video[4] = Info->VerticalResolution;
  Video[5] = 32;
  return EFI_SUCCESS;
}

#endif
'''
            bv.write_text(new_bv, encoding='utf-8', newline='\n')
            print("  [+] Patched BootVideo.h (added BltOnly / headless fallback & debug logging)")

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
