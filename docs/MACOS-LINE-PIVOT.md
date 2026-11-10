# macOS 线切换（pivot）说明

## 为什么放弃在 iPadOS 线上继续

当前 `UniXNU`（本仓库）走的是 `apple-oss-distributions/xnu` 的 **iPadOS 分支**
（`xnu-10063.141.1`）。这条源码里**没有 macOS 的 vfs 模型**：

- `bsd/conf/files` 中 `firmlink` / `rosv` / `dataless` / `union_mounts` 匹配数为 0；
- 不存在 `bsd/vfs/vfs_firmlinks.c`；
- `config/` 下没有 `config_firmlinks`、`config_rosv_startup` 等选项文件。

因此 macOS 用户态的 `/private/var`（到 Data 卷的 firmlink）在这条内核上无法解析：
只读根上无法创建该目录（EROFS），打开 `config_firmlinks` 也无从编译。
这也是为什么 macOS 必须跑在 macOS 内核分支上。

已经在这台手机上验证通过、可复用的结论（属于 iPadOS 线）：

- 根卷（macOS 23G93 System 卷 `63E8D68F`）经真实 verified-root 策略认证后只读挂载；
- SystemOS cryptex（`069A2122`）经 owner cache 以 union 方式挂到 `/`，dyld carrier 授权通过；
- `DBRDISK1` 稀疏 Data seed 正常：内存盘 2GiB，APFS 容器被识别为 `disk4s1`；
- 卡点仅剩 macOS 的 firmlink/rosv 模型。

## 上游 macOS 线

`Droid-VM/macOS-DroidVM` 是 Droid-VM 的 macOS-on-DroidVM 线，由以下三部分组成：

| 角色 | 仓库 | 分支 |
| --- | --- | --- |
| 基础 UniXNU | `Droid-VM/UniXNU` | `wip/droidvm` |
| 设备仓库 | `Droid-VM/UniXNU-droidvm` | `wip/hackintosh` |
| 覆盖层（本仓库内容） | `Droid-VM/macOS-DroidVM` | `macOS` |

覆盖层通过 `overlay/droidvm/{patches/xnu,drivers,scripts}` 覆盖设备仓库，
再由 `scripts/apply-overlay-board.py` 合入。

设备仓库自带**一键构建器** `scripts/build-droidvm-all.py`，其步骤为：
`setup → volumes → policies → data-base → reference → kernel → package → tools → plugin → data → trust → payload → images`。
产物在 `out/droidvm/release/`：

- `droidvm-disk.img`：引导盘（UniXNU.efi、DarwinBoot.efi、kernel、ADT、trust、Data seed）；
- `os.img`、`systemos.img`；
- `release.json`（内容与哈希）。

其中 `data-base` 从 OS 自己的 `/private/var` 生成 Data seed，并把其 APFS 卷 UUID
写入 `CONFIG_XNU_OWNER_DATA_VOLUME_UUID` —— 正是我们在 iPadOS 线上手工补的那块。

## 下一步

1. 触发 `.github/workflows/pivot-macos-line.yml`（workflow_dispatch，未加密产物）。
   它按上面的三仓库组合 + 覆盖层执行 `build-droidvm-all.py`，上传 `droidvm-release`。
2. 从产物取 `droidvm-disk.img`，按现有流程推到手机：
   `adb push droidvm-disk.img /sdcard/DroidVM/MacOS/boot.img`。
3. `os.img` / `systemos.img` 若与本机一致可复用；否则同样覆盖推送。
4. 之后按 `tools/rig/fresh-deploy.sh` 的说明（上游）配置 VM 磁盘与启动参数。

## 成本与风险

- 单次构建约 3～5 小时（14.79GB IPSW、Metal 插件与 ownervisor 工具链）；
- 需要 macOS runner（`hdiutil`、Xcode 工具链）；
- 上游产物默认加密上传（需要 `ARTIFACT_KEY`）；本工作流改为明文产物以简化部署；
- 本仓库（iPadOS 线）的改动与结论保留，作为对照与回退路径。
