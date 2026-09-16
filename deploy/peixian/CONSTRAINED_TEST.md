# 单服务器受限资源测试包装器

`constrained-test.py` 用于在支持 Linux cgroup v1 的共享服务器上，为**独立合成部署**建立 16 CPU、32 GiB 口径的测试边界。它包裹现有部署管理器和宿主 Worker，不修改平台正常部署入口，也不重配 Docker 守护进程。

这是测试适配工具，不是正式生产环境的 cgroup 部署方案。本文说明使用方式和证据边界，不记录某次测试成绩；实际容量、活动任务数和通过情况以对应验收报告为准。

## 1. 使用前提

- 在 Linux 主机上运行，使用 cgroup v1 和 Docker cgroupfs 驱动。本工具假定控制器位于 `/sys/fs/cgroup/cpu,cpuacct`、`memory`、`cpuset`、`pids`，不适用于 cgroup v2 或其他挂载布局。
- CPU 控制器支持 CFS quota，memory 控制器提供 `memory.memsw.limit_in_bytes`。缺失控制器、计数文件或写权限时应处理具体环境问题，不能跳过限制继续声称受限测试通过。
- 当前 cpuset 至少包含 16 个 CPU。工具使用其中编号最高的 16 个 CPU；这些 CPU 并没有被独占，其他服务仍可能在相同 CPU 上运行。
- 初始化父组和将 Worker 加入父组需要相应系统权限，通常由本次测试专用的 root 管理会话执行。Python 使用已安装部署依赖的专属虚拟环境。
- 使用独立部署标识、数据目录、端口、网络池、凭据和合成账号。不得复用生产配置、生产控制卷或生产 Worker 状态目录。
- 配置必须为 `version: 2`；`deployment_id` 必须匹配 `loadtest-[a-z0-9-]{1,30}`；`capacity_policy.host_memory_reserve_mib` 至少为 `4096`。
- 镜像、证书、网络池和资源预算继续经过现有部署预检查。测试配置的账号数量和单账号配额需要据资源画像确定，不能仅修改目标账号数来表示已经有相应容量。

可从 [50 账号候选配置](server/platform.50-io.example.json) 复制出一份私密测试配置，再设置独立字段。该示例保留的单账号配额不保证能放入本工具的资源边界；预检查拒绝时应保留失败记录。

本次边界要求相关配置至少包含以下内容；这段不是可以独立启动的完整配置：

```json
{
  "version": 2,
  "profile": "single-host-50-io",
  "deployment_id": "loadtest-r1",
  "capacity_policy": {
    "host_memory_reserve_mib": 4096
  }
}
```

## 2. 实际约束与容量计算

| 项目 | 工具行为 | 解释 |
| --- | --- | --- |
| CPU quota | 周期 `100000` μs、配额 `1600000` μs | 应用父组累计 CPU 时间上限相当于 16 CPU |
| CPU 集合 | 从当前 cpuset 选择 16 个 CPU | 限制可运行 CPU 范围，不设置 CPU 独占 |
| 应用内存 | 父组 memory 上限为 28 GiB | 包含父组内所有账号容器、Control、HTTPS 和 Worker 的内存记账 |
| 应用内存与交换合计 | 父组 memsw 上限同为 28 GiB | 不将交换空间加到容量预算中 |
| 主机余量 | 另列 4 GiB accounting reserve | 形成 32 GiB 预算口径；不是在父组之外实际锁定的一块独占内存 |
| 进程数 | 父组 `pids.max=16384` | 限制父组内累计任务数；各容器原有进程限额仍然有效 |
| 单容器资源 | 保留配置中的 CPU、内存和进程上限 | 父组总上限不会替代各容器限额 |

部署预检查和 Worker 容量检查使用：

```text
可用于计算的 CPU = min(Docker 报告的真实 CPU 数, 16)
可用于计算的内存 = min(Docker 报告的真实内存, 32 GiB)
```

宿主资源更大时不能借用额外容量使预算通过；宿主资源更小时也不会虚增到 16 CPU、32 GiB。预算要求仍由原有容量函数计算，CPU 共享策略必须显式配置，内存总预算不能取消。

容量函数每次执行前会重新验证父组限制，结果中的 `capacity_source` 为 `verified_test_parent`。配置余量高于 4 GiB 时，配置预算会更保守，但本工具的应用父组上限仍固定为 28 GiB。不要把规划余量与操作系统硬隔离混为一谈。

## 3. 初始化并启动独立部署

以下命令在代码仓库根目录执行。将路径替换为本次测试的实际文件，配置文件中不得引用生产数据目录。示例使用 Bash；`TEST_PYTHON`、`TEST_CONFIG` 只是当前终端的命令参数。

```bash
TEST_PYTHON="./worker-venv/bin/python"
TEST_CONFIG="/etc/agent-platform-loadtest/platform.json"
```

### 3.1 创建或核对专属父组

```bash
"$TEST_PYTHON" deploy/peixian/constrained-test.py init-group \
  --config "$TEST_CONFIG"
```

四个控制器分别使用与 `deployment_id` 同名的父组。只有四组均不存在时才新建并设置限制；已有任一组时，工具只核对全部预期限制，不覆盖已有值，也不自动修补部分初始化状态。

任务父组、控制器目录或计数文件存在不允许的符号链接时会拒绝操作。初始化失败后保留现场，先确认哪些资源属于本次测试，不通过删除整个控制器目录或放宽限制来重试。

### 3.2 初始化私密配置、预检查并启动 Control 与 HTTPS

```bash
"$TEST_PYTHON" deploy/peixian/constrained-test.py manage \
  --config "$TEST_CONFIG" --manage-action init

"$TEST_PYTHON" deploy/peixian/constrained-test.py manage \
  --config "$TEST_CONFIG" --manage-action check

"$TEST_PYTHON" deploy/peixian/constrained-test.py manage \
  --config "$TEST_CONFIG" --manage-action up
```

`manage` 可用子动作是 `init`、`check`、`render`、`up`、`status`、`stop`。需要单独检查生成的 Compose 时使用 `render`。初始化凭据会写入本配置的私密目录，不要将凭据内容复制到报告或 Git。

测试期间启动和重建本部署，应继续经过本包装器；直接调用普通 `platform-manage.py` 可能重新生成没有测试父组的 Compose，失去本次约束。

### 3.3 启动专属 Worker

在独立的测试终端前台运行：

```bash
"$TEST_PYTHON" deploy/peixian/constrained-test.py worker \
  --config "$TEST_CONFIG"
```

Worker 进入循环前先验证父组，再将自身 PID 写入 CPU、memory、cpuset 和 pids 父组的 `cgroup.procs`。它为账号生成的 Agent、Gateway、Relay Compose 同样带测试父组。

只检查一次任务领取与处理流程时，可追加 `--once`。一次模式不保证存在任务，也不表示全部账号已经开通：

```bash
"$TEST_PYTHON" deploy/peixian/constrained-test.py worker \
  --config "$TEST_CONFIG" --once
```

如需以服务形式持续运行，应新建独立测试服务并使用上述包装器命令，不修改生产 Worker 服务，也不要为同一测试状态目录同时启动两个 Worker。Worker 必须持续在线，管理员创建合成账号后才能处理环境开通任务。

## 4. 为什么必须核对实际进程路径

Compose 注入的值必须是绝对路径，例如：

```yaml
cgroup_parent: /loadtest-r1
```

部分 Docker／containerd 组合会把相对的 `loadtest-r1` 解析到守护进程所在的 cgroup 子树，例如 `/system.slice/containerd.service/loadtest-r1/...`。即使 Compose 写了父组名字，实际 CPU、memory 或 pids 也可能未进入预期受限父组。仅检查配置文本或 `docker inspect` 的声明不足以证明约束生效。

工具只对所有服务均带有本测试 `peixian.deployment` 标签的 Compose 注入父组；缺少标签或夹带其他部署服务会整份拒绝。注入范围覆盖 Control、HTTPS，以及每账号的 Agent、Gateway、Relay。

查看父组限制和累计计数：

```bash
"$TEST_PYTHON" deploy/peixian/constrained-test.py status \
  --config "$TEST_CONFIG"
```

同时核对实际运行容器路径：

```bash
"$TEST_PYTHON" deploy/peixian/constrained-test.py audit \
  --config "$TEST_CONFIG"
```

`audit` 会读取本部署运行容器的 Docker 元数据，并读取其宿主 PID 的 `/proc/<pid>/cgroup`。要求声明父组为绝对路径，且 `memory`、`cpu`、`cpuacct`、`cpuset`、`pids` 的实际路径全部位于该测试父组下。

审计重新检查部署标签、运行状态、PID 和库存数量；Docker 查询有超时限制。无运行容器、进程消失、控制器缺失、相似名称前缀或实际路径逃逸均不能返回成功。

审计结果只返回父组状态、计数和验证结论，不输出容器完整 inspect、原始 PID 或各容器路径。它只覆盖调用时发现的运行容器，不能证明已经存在目标数量的账号环境，也不代替 Worker 所属父组检查。应结合 Worker 进程身份和对应父组的 `cgroup.procs` 在宿主侧核对；不要在可公开报告中粘贴完整进程清单。

开始负载前、增加一批账号后、容器重建后和测试结束时都应执行审计。发现漂移后停止增加负载，受影响时段不能作为受限容量通过的证据。

## 5. 采样与证据解释

父组 `status` 用于观察受限应用整体；`platform-sample.py --cgroup` 用于观察各容器，例如：

```bash
"$TEST_PYTHON" deploy/peixian/platform-sample.py sample \
  --config "$TEST_CONFIG" --cgroup --samples 12 --interval 5 \
  --output /reports/loadtest-resources-NEW.json
```

输出必须使用已准备目录下的新文件，并位于本配置的数据根目录之外。已有文件不会被覆盖。采样和负载应分开运行，记录采样周期及探针开销。

- 采样显式标注 cgroup v1／v2；v1 的 `memory.current`、`memory.peak`、`memory.max` 分别映射原生 usage、max_usage 和 limit 字段。字段缺失时是未知，不是零。
- v1 `memory.failcnt` 是达到限制的计数，不是 OOM kill 计数。`memory.oom_control` 中没有 `oom_kill` 时，不能把 failcnt 或缺失字段替换为零次 OOM。Docker 的 OOMKilled 状态和重启计数另行检查。
- v1 CPU 时间使用纳秒，v2 `cpu.stat` 时间字段使用微秒；cpuacct 的时钟滴答字段另有单位说明。比较采样间增量时必须保持相同口径。
- 峰值与失败计数是累计值，工具不重置。应保留开始和结束样本，说明计数是否包括准备阶段；新建或重建容器后的计数不能与旧容器直接相减。
- `engine.MemAvailable`、`engine.SwapFree`、`engine.SwapTotal` 来自 `/proc/meminfo`，反映可见主机／Docker 引擎内存视图，**不是容器内存上限，也不是本次测试剩余的 32 GiB**。容器上限看 cgroup 和 Docker 限制，应用总上限看父组。
- 独立运行的 `platform-sample.py` 仍按 Docker 实际宿主资源生成其 `capacity` 部分，不经过本包装器的 16／32 裁剪。它的宿主预算结论不能替代 `constrained-test.py manage --manage-action check` 的受限预算结果。

## 6. 共享服务器上的限制

受限父组包含账号应用容器、Control、HTTPS 和专属 Worker。Docker／containerd 守护进程、部分宿主辅助进程、宿主采样脚本、临时 Docker 探针容器及压测客户端并不自动加入该父组；它们在父组外的资源消耗应单独说明。`docker exec` 进入被测容器执行的探针则会占用该容器和应用父组资源。

4 GiB accounting reserve 是对父组外开销的预算说明，不是这些进程共同受到的另一条 4 GiB 硬限制。若父组外实际开销超出假设，报告应记录差额，不能据应用父组未超限直接宣称整套平台满足总预算。

同宿主的其他服务仍会影响 CPU 调度、磁盘、网络、页缓存和全机内存压力。父组中的 cpuset 不提供 CPU 独占，28 GiB memory 上限也不保证宿主始终可提供相同的空闲物理内存。此类测试应描述为“共享宿主上的受限应用测试”，不能等同于独占 16 核、32 GiB 虚拟机或物理机验收。

此外，活动任务数、模型响应时间、插件接口等待时间和 SSE 订阅数是不同指标。父组审计通过只证明观察时刻的资源归属正确，不证明目标并发、模型效果、生产隔离或长时间稳定性通过。

## 7. 停止、保留与再次测试

测试结束时先停止压测输入，等待已有任务结束，按测试账号逐个暂停需要停止的环境并等待 Worker 完成操作。随后结束专属 Worker，再停止本配置 Control／HTTPS：

```bash
"$TEST_PYTHON" deploy/peixian/constrained-test.py manage \
  --config "$TEST_CONFIG" --manage-action stop
```

`manage stop` 使用平台 Compose，只停止其中的 Control／HTTPS，不会自动清空或停止所有账号环境。暂停账号、停止 Worker、停止平台入口和删除数据是不同操作，需分别核对。

本工具没有自动清理父组、删除账号、删除网络或删除持久卷的命令。测试数据、私密配置、累计计数和报告应按本次测试记录保留。不要直接删除 `/sys/fs/cgroup` 下的上层目录，不要重启或重置全机 Docker 来清理测试，更不能通过关闭内存检查来恢复负载。

重启宿主后父组可能需要重新初始化；已有 Docker 容器是否重新落入正确父组必须再次审计，不能沿用重启前结论。需要采用新的配置、配额或镜像时，记录变更点并重新完成受限预检查和实际路径审计。

更多平台操作见 [Linux 单机部署说明](server/README.md)，测试与验收口径见 [第一轮实施指南](../../services/peixian-control/docs/HARDENING_R1.md)。
