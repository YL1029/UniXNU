# ArmCpu (DroidVM board override)

Board-local copy of the upstream `drivers/ArmCpu` driver (UniXNU/ArmCpu at
`1951cc8444b340d7d8879e9418220cf29eb711d7`), taken because the device repository
module wins over the base module of the same name.

The only difference from upstream is diagnostics: every silent `return false`
of the GIC bring-up path records the failing step in `gGicFailStage`, and
`probe()`/`start()` log why a CPU node was skipped or rejected. The virtual
board needs this because a rejected `ArmCpu` is not an error by itself: IOKit
falls through to the next matching personality, and on this board that is
`AppleARMCPU` from the prelinked `com.apple.driver.AppleARMPlatform` kext, which
then panics with `"CPU configuration in device tree is invalid"`.

Log lines to expect on the serial console:

```
ArmCpu: probe accepts cpu0: physical 0, logical 0
ArmCpu: start cpu0: physical 0, logical 0, secondary 0, skip-gic 0
ArmCpu: boot CPU 0 registered (physical 0, cluster 0)
```

or, when bring-up fails:

```
ArmCpu: probe skips cpu0: physical 0 maps to logical -1, boot is 0, sheng-smp 0
ArmCpu: GIC bring-up failed at step 2 (intc reg/ranges/compatible invalid); no CPU driver will take cpu0
```

Re-sync this file with upstream whenever `drivers/ArmCpu` changes; the
instrumentation is the only intended difference.
