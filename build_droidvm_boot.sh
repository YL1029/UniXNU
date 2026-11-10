#!/usr/bin/env bash
# ==============================================================================
# UniXNU DroidVM macOS 引导盘 (boot.img) 一键构建脚本
# 请在 macOS (Apple Silicon 或 Intel Mac，系统推荐 macOS 14/15) 上运行此脚本
# ==============================================================================

set -euo pipefail

# 切换到脚本所在目录（UniXNU 根目录）
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "================================================================="
echo "   UniXNU DroidVM (Xiaomi 15 / Snapdragon 8 Elite) 引导盘构建"
echo "================================================================="

# 1. 检查操作系统
if [ "$(uname -s)" != "Darwin" ]; then
    echo "❌ 错误: 此脚本必须在 macOS 系统上运行（内核编译依赖苹果 clang/ld64 工具链）。"
    exit 1
fi

echo "✅ 系统检测: macOS $(sw_vers -productVersion) ($(uname -m))"

# 2. 检查 Xcode 与内核编译工具链 (migcom, iig)
DEVELOPER_DIR="$(xcode-select -p 2>/dev/null || true)"
if [ -z "$DEVELOPER_DIR" ]; then
    echo "❌ 错误: 未检测到 Xcode 开发工具，请在终端执行: xcode-select --install"
    exit 1
fi

# 检查是否包含 XNU 内核编译必需工具 (migcom, iig)
if ! xcrun -find migcom >/dev/null 2>&1 || ! xcrun -find iig >/dev/null 2>&1; then
    echo "⚠️ 当前开发者路径 ($DEVELOPER_DIR) 缺少 migcom 或 iig（极简版 CommandLineTools 不含这些核心工具）。"
    if [ -d "/Applications/Xcode.app/Contents/Developer" ]; then
        echo "==> 检测到已安装完整 Xcode.app，正在自动切换开发者路径到 Xcode..."
        sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
        export DEVELOPER_DIR="/Applications/Xcode.app/Contents/Developer"
        echo "✅ 已切换至: /Applications/Xcode.app/Contents/Developer"
    elif [ -d "/Applications/Xcode-beta.app/Contents/Developer" ]; then
        echo "==> 检测到已安装 Xcode-beta.app，正在自动切换开发者路径..."
        sudo xcode-select -s /Applications/Xcode-beta.app/Contents/Developer
        export DEVELOPER_DIR="/Applications/Xcode-beta.app/Contents/Developer"
        echo "✅ 已切换至: /Applications/Xcode-beta.app/Contents/Developer"
    else
        echo "❌ 错误: 未找到完整版 /Applications/Xcode.app"
        echo "   XNU 内核的 DriverKit 和 Mach 接口生成器 (iig, migcom) 必须依赖完整版 Xcode。"
        echo "   - 如果你已经安装了 Xcode，请执行: sudo xcode-select -s /你的Xcode路径/Contents/Developer"
        echo "   - 如果尚未安装，请从 Mac App Store 下载安装 Xcode 后重试。"
        exit 1
    fi
fi
echo "✅ Xcode 工具链完整 (包含 migcom, iig): $(xcode-select -p)"

# 3. 检查并安装 Homebrew 依赖
echo "==> 检查构建依赖工具 (Homebrew)..."
MISSING_DEPS=()
for dep in llvm cmake ninja unifdef mtools dtc; do
    if ! command -v "$dep" >/dev/null 2>&1; then
        MISSING_DEPS+=("$dep")
    fi
done

if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
    echo "⚠️ 缺少以下依赖工具: ${MISSING_DEPS[*]}"
    if command -v brew >/dev/null 2>&1; then
        echo "==> 正在使用 Homebrew 自动安装依赖..."
        brew install llvm lld cmake ninja unifdef mtools dtc
    else
        echo "❌ 未安装 Homebrew，请先安装 Homebrew 或手动安装: ${MISSING_DEPS[*]}"
        exit 1
    fi
else
    echo "✅ 基础依赖工具齐全 (llvm, cmake, ninja, unifdef, mtools, dtc)"
fi

# 确保 llvm 路径在 PATH 优先位置
if [ -d "/opt/homebrew/opt/llvm/bin" ]; then
    export PATH="/opt/homebrew/opt/llvm/bin:$PATH"
elif [ -d "/usr/local/opt/llvm/bin" ]; then
    export PATH="/usr/local/opt/llvm/bin:$PATH"
fi

# 4. 验证 device 目录
DEVICE_DIR="$ROOT/device"
if [ ! -d "$DEVICE_DIR" ]; then
    echo "❌ 错误: 未找到 $DEVICE_DIR 目录，请确保已完整复制 UniXNU 文件夹。"
    exit 1
fi

# 5. 配置与获取源码
echo "==> [步骤 1/4] 配置板级目标: droidvm_defconfig..."
python3 "$ROOT/unixnu" defconfig droidvm_defconfig -D "$DEVICE_DIR"

echo "==> [步骤 2/4] 获取依赖源码 (feeds)..."
python3 "$ROOT/unixnu" fetch

# 真实的 verified-root 策略（os + SystemOS 的 manifest 与 owner 公钥）必须与手机上的两个镜像逐块哈希一致。
# CI 没有那 16GB 原始镜像，因此从 release 资源下载（由镜像所在机器用 VerifiedRoot/tools/manifest.py 生成并签名）。
# 缺少它时构建会退回 fixture 策略，内核只把磁盘当作 unverified，SystemOS 的 owner 挂载会被拒绝（EAUTH）。
VR_INPUTS_URL="${VR_INPUTS_URL:-https://github.com/YL1029/UniXNU/releases/download/verified-root-inputs}"
VR_INPUTS_DIR="$ROOT/out/droidvm/tree/build/verified-root-inputs"
echo "==> 获取 verified-root 策略 (os/systemos manifest)..."
mkdir -p "$VR_INPUTS_DIR"
for name in os.manifest.bin systemos.manifest.bin trusted-key.bin os.samples.bin inputs.json; do
    curl -fsSL --retry 3 "$VR_INPUTS_URL/$name" -o "$VR_INPUTS_DIR/$name" || {
        echo "❌ 错误: 无法下载 verified-root 输入 $name"; exit 1; }
done
python3 - "$VR_INPUTS_DIR" <<'PY'
import json, sys
from pathlib import Path
directory = Path(sys.argv[1])
meta = json.loads((directory / 'inputs.json').read_text())
for name in ('os', 'systemos'):
    entry = meta[name]
    size = (directory / f'{name}.manifest.bin').stat().st_size
    print(f"  {name}: manifest {size} bytes, volume {entry['volume_uuid']}, "
          f"{entry['block_count']} blocks x {entry['block_bytes']}")
PY

# 确保源码工作目录状态纯净（注意：绝不清除 out/feeds，只重置 xnu-work 临时目录）
XNU_WORK="$ROOT/out/droidvm/tree/.cache/xnu-work"
if [ -d "$XNU_WORK/.git" ]; then
    echo "==> 检查 XNU 临时工作目录，重置以防残留补丁冲突..."
    git -C "$XNU_WORK" reset --hard HEAD >/dev/null 2>&1 || true
    git -C "$XNU_WORK" clean -fdx >/dev/null 2>&1 || true
fi

# 6. 构建 XNU 内核
echo "==> [步骤 3/4] 构建修补版 XNU 4KiB 内核 (预计需要 10~25 分钟)..."
TREE_DIR="$ROOT/out/droidvm/tree"
STARTUP_RECORD="$TREE_DIR/build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/osfmk/DEVELOPMENT/startup.o.json"
if [ ! -f "$STARTUP_RECORD" ]; then
    echo "==> 首次从零构建：执行 bootstrap 阶段生成头文件与编译记录..."
    python3 "$ROOT/unixnu" build kernel || echo "==> Bootstrap 阶段完成"
    if [ -f "$ROOT/scripts/placeholder-archives.py" ]; then
        python3 "$ROOT/scripts/placeholder-archives.py" "$TREE_DIR"
    fi
fi
python3 "$ROOT/unixnu" build kernel

# 7. 构建 EFI 引导程序包 (UniXNU.efi / DarwinBoot.efi)
echo "==> [步骤 4/4] 构建 UEFI 引导程序与驱动 (package)..."
if [ -f "$ROOT/scripts/patch-darwinboot.py" ]; then
    echo "==> 为 DarwinBoot 应用 DroidVM 兼容性补丁 (RGB 像素格式与 EL2 支持)..."
    python3 "$ROOT/scripts/patch-darwinboot.py" "$ROOT/drivers/DarwinBoot"
    if [ -d "$ROOT/out/droidvm/tree/drivers/DarwinBoot" ]; then
        python3 "$ROOT/scripts/patch-darwinboot.py" "$ROOT/out/droidvm/tree/drivers/DarwinBoot"
    fi
fi
python3 "$ROOT/unixnu" build package

# 8. 组装 boot.img 引导磁盘
echo "==> 正在组装 EFI 引导盘 boot.img..."

KERNEL_MACHO="$ROOT/out/droidvm/kernel/kernel.macho"
if [ ! -f "$KERNEL_MACHO" ]; then
    KERNEL_MACHO="$(find "$ROOT/out" -name "kernel.macho" | head -n 1)"
fi

UNIXNU_EFI="$(find "$ROOT/out" -name "UniXNU.efi" | head -n 1)"
DARWINBOOT_EFI="$(find "$ROOT/out" -name "DarwinBoot.efi" | head -n 1)"

if [ ! -f "$KERNEL_MACHO" ]; then
    echo "❌ 错误: 未找到构建出的 kernel.macho，请检查上一步的编译日志。"
    exit 1
fi

if [ -z "$UNIXNU_EFI" ] || [ ! -f "$UNIXNU_EFI" ]; then
    echo "❌ 错误: 未找到 UniXNU.efi，构建中止！"
    exit 1
fi

if [ -z "$DARWINBOOT_EFI" ] || [ ! -f "$DARWINBOOT_EFI" ]; then
    echo "❌ 错误: 未找到 DarwinBoot.efi，构建中止！"
    exit 1
fi

echo "✔ 发现 UniXNU.efi: $UNIXNU_EFI"
echo "✔ 发现 DarwinBoot.efi: $DARWINBOOT_EFI"
echo "✔ 发现 kernel.macho: $KERNEL_MACHO"

# AppleARMPlatform 的 AppleARMCPU personality 面向真实 Apple 芯片：虚拟 /cpus 节点一旦由
# 它接手，它就会因缺少 Apple 专有 CPU 属性而 panic（AppleARMCPU.cpp:111）。这里只从预链接
# 元数据里摘掉该 personality，kext 本体与其他 16 个 personality 保持不变。
# AMFI 的 ConfigurationSettings 只有在 kern.hv_vmm_present 为 0 时才通过 ApplePMGRNub 读 PMGR/AON
# 的开发者模式状态；虚拟板没有 PMGR 硬件，那条路径会 panic("AMFI: No PMGR?")。ADT 的
# /defaults/vmm-present 让内核报告 kern.hv_vmm_present，AMFI 随即走 “Booted in a VM” 分支。
echo "==> 移除预链接 kext 中会抢占虚拟 CPU 节点的 AppleARMCPU personality..."
python3 "$ROOT/device/scripts/patch-prelink-personalities.py" \
    --kernel "$KERNEL_MACHO" \
    --drop com.apple.driver.AppleARMPlatform:AppleARMCPU

STAGE_DIR="$ROOT/out/esp_stage"
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR/EFI/BOOT"
mkdir -p "$STAGE_DIR/EFI/UniXNU/Payloads"

# 复制 EFI 核心与驱动
cp "$UNIXNU_EFI" "$STAGE_DIR/EFI/BOOT/BOOTAA64.EFI"
cp "$DARWINBOOT_EFI" "$STAGE_DIR/EFI/UniXNU/Payloads/DarwinBoot.efi"

# 复制内核
cp "$KERNEL_MACHO" "$STAGE_DIR/EFI/UniXNU/Payloads/kernel.macho"

# 生成设备树 kernel.macho.adt (DarwinBoot 加载 XNU 所必需)
echo "==> 正在生成 DroidVM 设备树 (kernel.macho.adt)..."
# /private/var 的 Data 卷必须可写，而 crosvm 的磁盘只接受只读盘，所以项目用一块内存盘：
# DBRDISK1 稀疏格式（只保存非零 4K 页），由 NativeRamBlock 展开成 APFS 容器。
# seed 由 .github/workflows/macos-data-seed.yml 在 macOS runner 上从安装器模板生成并发布为 release 资源。
DATA_SEED_URL="${DATA_SEED_URL:-https://github.com/YL1029/UniXNU/releases/download/macos-data-seed/scratch-data.img}"
DATA_SEED="$STAGE_DIR/EFI/UniXNU/Payloads/scratch-data.img"
ADT_RAMDISK=""
INITRD_LINE=""
if curl -fsSL --retry 3 "$DATA_SEED_URL" -o "$DATA_SEED"; then
    echo "==> Data seed: $(( $(wc -c < "$DATA_SEED") >> 20 )) MiB (packed)"
    ADT_RAMDISK="--data-ramdisk packed"
    INITRD_LINE='initrd = "Payloads/scratch-data.img"'
else
    rm -f "$DATA_SEED"
    echo "⚠️  警告: 未取到 Data seed，/private/var 将缺失（内核会在 owner Data 挂载处 panic）"
fi
# GIC 重分发器区域按 VM 的 vCPU 数描述（手机端 vms.json 的 cpu_count，当前 4）：
# crosvm/Gunyah 在 GICD 之下为每个 vCPU 放一个 0x20000 帧，ArmCpu 在该区域内按 GICR_TYPER 亲和性找自己的帧；
# 而 /cpus 仍只描述引导 CPU（--smp 1），两者的数量本来就可以不同。
GIC_CPUS="${GIC_CPUS:-4}"
# 根卷 = os.img 里的 OS 卷。当前 os.img 由 macOS 14.6.1 (23G93) 恢复镜像的 OS.dmg 展开而来，
# 其 System 卷 UUID 为 63E8D68F-...（macOS 线 run-macos-vm.py 里 pin 的 OS_UUID）。
# 没有 /chosen/root-matching 时 IOKitBSDInit 只会打印 "Still waiting for root device" 直到超时 panic。
ROOT_VOLUME_UUID="${ROOT_VOLUME_UUID:-63E8D68F-1310-4609-8FD8-CA9501AAFAD4}"
python3 "$ROOT/device/scripts/make-virt-adt.py" \
    --machine crosvm \
    --timebase 19200000 \
    --ipad-identity \
    --smp 1 \
    --gic-cpus "$GIC_CPUS" \
    --vmm-present \
    --root-match-volume-uuid "$ROOT_VOLUME_UUID" \
    ${ADT_RAMDISK} \
    --output "$STAGE_DIR/EFI/UniXNU/Payloads/kernel.macho.adt"

if [ ! -f "$STAGE_DIR/EFI/UniXNU/Payloads/kernel.macho.adt" ]; then
    echo "❌ 错误: 未能生成 kernel.macho.adt！"
    exit 1
fi
echo "✔ 成功生成 kernel.macho.adt"

# 生成启动配置 unixnu.toml
cat << EOF > "$STAGE_DIR/EFI/UniXNU/unixnu.toml"
version = 1
[boot]
timeout = 3
default = "xnu"

[kits]
autoload = false

[[driver]]
path = "Payloads/DarwinBoot.efi"

[[entry]]
id = "xnu"
title = "DroidVM: macOS on Xiaomi 15 (SM8750 Gunyah)"
type = "xnu"
path = "Payloads/kernel.macho"
${INITRD_LINE}
args = "-v serial=3 debug=0x14e amfi_get_out_of_my_way=1 ipc_control_port_options=0"
EOF

# 使用 mtools 打包成标准的 FAT32 ESP 引导镜像
OUTPUT_BOOT_IMG="$ROOT/boot.img"
rm -f "$OUTPUT_BOOT_IMG"

# ESP 要同时放下内核（内嵌 os/systemos 的 verified-root 策略后约 180MB）和 Data seed（最多 256MiB）。
BOOT_SIZE_MIB=512
STAGE_BYTES=$(du -sk "$STAGE_DIR" | awk '{print $1}')
if [ "$STAGE_BYTES" -gt $((BOOT_SIZE_MIB * 1024 * 95 / 100)) ]; then
    echo "❌ 错误: payload 占 ${STAGE_BYTES} KiB，超过 ${BOOT_SIZE_MIB} MiB ESP 的 95%，请提高 BOOT_SIZE_MIB"
    exit 1
fi
truncate -s "${BOOT_SIZE_MIB}M" "$OUTPUT_BOOT_IMG"
mformat -i "$OUTPUT_BOOT_IMG" -F -v "UNIXNUESP" -C -T $((BOOT_SIZE_MIB * 2048)) ::
mcopy -s -i "$OUTPUT_BOOT_IMG" "$STAGE_DIR"/* ::/

echo ""
echo "================================================================="
echo "🎉 恭喜！引导盘构建完成！"
echo "📁 输出引导文件: $OUTPUT_BOOT_IMG"
echo "📏 文件大小: $(ls -lh "$OUTPUT_BOOT_IMG" | awk '{print $5}')"
echo "================================================================="
echo "下一步操作："
echo "1. 将上面生成的 boot.img 复制到手机的 /sdcard/DroidVM/MacOS/boot.img"
echo "2. 打开手机上的 DroidVM App，点击 macOS (UniXNU) 启动虚拟机！"
echo "================================================================="
