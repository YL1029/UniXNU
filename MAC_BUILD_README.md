# Mac 电脑一键编译 DroidVM macOS 引导盘 (boot.img) 指南

本项目用于在搭载**高通骁龙 8 至尊版（SM8750）的小米 15** 上，通过 Qualcomm Gunyah 硬件虚拟化引导 macOS。

由于 macOS 内核（XNU）和驱动构建依赖苹果原厂的 `clang`、`ld64` 和 `iphoneos` SDK 工具链，因此本步骤需要在 **Mac 电脑**（Apple Silicon M系列芯片或 Intel Mac 均可，推荐 macOS 14 Sonoma 或 macOS 15 Sequoia）上执行。

---

## 🛠️ 第一步：前置准备（在 Mac 上）

1. **安装 Xcode Command Line Tools**：
   打开 Mac 上的 **终端（Terminal）**，执行以下命令并同意安装弹窗：
   ```bash
   xcode-select --install
   ```

2. **安装 Homebrew（若未安装）**：
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```

---

## 🚀 第二步：将 `UniXNU` 目录复制到 Mac 并一键编译

1. 将 Windows PC 上的整个 `UniXNU` 文件夹拷贝到 Mac 的任意位置（例如拷贝到 Mac 的 `Downloads` 或桌面）。
2. 在 Mac 终端中进入该目录：
   ```bash
   cd ~/Downloads/UniXNU
   ```
3. 赋予执行权限并直接运行编译脚本：
   ```bash
   chmod +x build_droidvm_boot.sh
   ./build_droidvm_boot.sh
   ```

### 脚本全自动处理的事情：
- 自动检测并安装所需的依赖包（`llvm`, `lld`, `cmake`, `ninja`, `unifdef`, `mtools`, `dtc` 等）。
- 自动载入小米 15 适配板级配置（`droidvm_defconfig`）。
- 自动应用 4KiB 内存页表补丁与虚拟化驱动（`NativeMetal`、`NativeVirtioBlock`、`ArmVirtPlatform` 等）。
- 自动编译构建生成 `kernel.macho` 与 EFI 加载程序（`UniXNU.efi`、`DarwinBoot.efi`）。
- 最终自动将它们打包生成 **`boot.img`** 引导镜像（大小约 128MB，放置在 `UniXNU/boot.img`）。

---

## 📱 第三步：将 `boot.img` 放入手机并开机

编译成功后：
1. 将 Mac 上生成的 `UniXNU/boot.img` 文件通过 USB 数据线（或局域网共享/微信/QQ）传到小米 15 手机上。
2. 放入手机内置存储路径：
   ```
   /sdcard/DroidVM/MacOS/boot.img
   ```
3. 打开手机上的 **DroidVM App**，在虚拟机列表中找到 **`macOS (UniXNU)`**，点击 **启动（运行）** 即可！
