# CLP1协议（途记1.5.1，兼容旧数据）

本版未改动协议、口令、加密方式或schema，与1.3.0/1.2.0完全互通。**1.5.0起路径库里的文件名改为可读名**（形如`2026-09-24_1355_连续_115点.clp`，`mode=single`写「单点」，重名追加`_2`/`_3`）——这是存放位置与命名规则的变化，协议内容一字未变：文件头、加密方式、schema与字段都不受影响，旧文件照常读取。

- 文件头0—3字节ASCII CLP1；4—7字节大端迭代次数310000；8—23字节随机盐；24—35字节随机12字节nonce。
- 36字节头部全部作为AES-GCM AAD。其后为UTF-8 JSON的AES-256-GCM密文与16字节认证标签。
- PBKDF2-HMAC-SHA256，输出32字节。发行版使用双端共享的固定 UTF-8 互通口令；公开源码不包含原口令，需要构建者在未提交的本地配置中提供。每次导出仍使用新的随机盐与nonce。UI不提供密钥设置；内置密钥用于格式互通，不提供用户独立口令的保密隔离。
- JSON schema为nef-gps-track/1，createdUtcMs为UTC毫秒；points数组按t升序。每点保留t、lat、lon、alt、hacc、speed、bearing、provider。lat/lon为WGS84，alt是MSL米或null，hacc为原始定位精度米或null，speed米/秒，bearing度。
- smoothing=robust-stop-v2表示全程水平位置鲁棒平滑；rawPoints保留原始点，points保留同时间、同数量的平滑节点，correctionMeters是水平修正距离。海拔不冒充具有额外精度的测量。**points是第一步「滤掉GPS定位漂移」的结果**：1.4.2起由手机端在停止记录时完成并写进CLP，实现仍是TrackSmoother.java。新导出的CLP只含这一步结果与原始点，**不含curve**。
- mode="track"（缺省）或"single"。single必须只有一个点，明确允许桌面端将位置用于任意照片时刻；定位点自身t仍保留真实定位时刻。GPS写入时间始终取照片拍摄UTC。
- curve.version="pchip-4d-v2"（1.4.2及更早为pchip-4d-v1），**由电脑端按points生成，不再由手机端写出**（第二步「插值形成平滑曲线」自1.4.2起归电脑端，见windows/curve.py::build_curve）；times为严格递增UTC毫秒数组，values=[lat,unwrappedLon,alt]，slopes为同形状数组，导数单位为坐标单位/毫秒。经度先按短路径展开后插值，输出归一到[-180,180)。
- **v2的四维含义：海拔也是一条独立子曲线**。`curve.py`除水平子曲线外另建`alt`子曲线，**只以海拔已知的结点为节点**：两端已知海拔之间的缺失时段由前后已知海拔插值**跨过去**，不再整段取不到海拔；首个、末个已知海拔之外仍返回null（不外推、不臆造），整条轨迹一个已知海拔都没有时`alt`子曲线为空，海拔恒为null。旧版的判据是“任一端为None就整段返回None”，这正是v1升v2要修的问题。`alt`子曲线缺失结点处的值与其斜率为null。
- 区间a,b内令h=t[b]-t[a]、u=(t-t[a])/h。值为(2u³-3u²+1)y[a]+(u³-2u²+u)h*m[a]+(-2u³+3u²)y[b]+(u³-u²)h*m[b]。导数用PCHIP加权调和均值和端点限幅，具体实现见curve.py；手机端原有的TrackCurve.java在1.5.1已删除，不再是参考实现。
- **电脑端会先滤掉海拔噪声再建曲线**：`windows/smoothing.py::smooth_altitude()`对海拔轴做鲁棒IRLS（二阶差分粗糙度惩罚），结果写回`points[i]['alt']`并在载荷里标`altitudeSmoothing='robust-alt-v1'`；**`points`里的海拔是滤过的、`rawPoints`里的原始海拔是原值不动**。海拔平滑是电脑端第二步的一部分，不在手机端执行（见完整维护文档第7节）。
- 桌面端从验证后的节点重建曲线，避免信任外来系数；**文件里若带curve系数（1.4.1及更早导出）一律丢弃**，只按points重建；也不重复平滑已是robust-stop-v1/v2的数据（windows/smoothing.py::build_curves，旧名smooth_payload保留为别名）。**水平方向的一步**（`smoothing.py::_fit`）逐字节未改，它与手机端TrackSmoother.java的数值一致性由qa/test_v120.py::test_whole_route_horizontal_java_parity守护；v2新增的只有海拔平滑`smooth_altitude()`与`curve.py`的alt子曲线，不影响水平节点的数值。旧robust-stop-v1节点不重复平滑，仅新增曲线。长间隔允许插值且明确标注估算，不对track时间范围外外推。旧客户端不了解single语义，单点补录请双端同时升级。
- 不修改用户历史CLP。文件头、加密方式和schema保持兼容。
- **schema未变**（仍为nef-gps-track/1），因为clp_codec._parse_payload()本来就不校验curve，删掉curve不需要升版本号。双端兼容：旧CLP（含curve）在新电脑端照常读取，忽略系数后按节点重建，行为与1.4.1一致；新CLP（无curve）在旧电脑端（≤1.4.1）经smooth_payload()补上curve（旧版标识pchip-4d-v1），正常工作；手机端不导入CLP，无影响。**曲线版本从pchip-4d-v1升到pchip-4d-v2是1.5.1的第二步内部升级**（新增alt子曲线与海拔平滑），不涉及schema与字段：读旧CLP只按points重建为v2，旧电脑端读到新CLP仍按自己的v1规则重建，两边都能算出曲线坐标，差别只在缺失海拔时段能否取到海拔。合并模式同样不引入新字段（见完整维护文档8.3节）。
