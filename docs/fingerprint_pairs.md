# 指纹特征浏览（业务表驱动）

机器 A 部署本分支后即可使用「指纹对比」菜单。

## 主线流程（一条线）

```text
T_CAP_FP_DATA (图路径)
    → 选 cap_image_id
T_FEATURE_RECORD (特征路径，fp_image_id = cap_image_id)
    → 读 MinIO/本地 upload|templates
    → ISO 解码细节点 → 单栏叠加
```

| 表 | 用途 |
|----|------|
| `ara_fp_analyst.T_CAP_FP_DATA` | `fingerprint_image` = `upload/...` |
| `ara_fp_analyst.T_FEATURE_RECORD` | Bidiso→`feature_ara_data`；Neuiso→`feature_neuro_data` |

界面：

1. 顶栏选择能访问 `ara_fp_analyst` 的数据库连接
2. 左侧树按 `dataset_code` 分组，叶子为 `cap_image_id`
3. 右侧单栏叠加细节点；第二栏占位预留（配对关联表就绪后 `panels.length=2`）

导入 zip **仍会**写入本系统 `image_info` / `fingerprint_*`；左侧树只读业务表，因此需开启**路径写回**后样本才会出现在树上。

## 功能

1. 导入 batmatch_out 风格 zip（可选路径写回业务表）
2. 按 `dataset_code` / `cap_image_id` 筛选业务样本
3. 勾选 Bidiso / neuiso 即时叠加细节点
4. API 载荷使用 `panels[]`：本期 `mode=single`；以后 `mode=pair` 不改解码核心

## 存储

| 类型 | 路径 |
|------|------|
| 指纹 bmp | `upload/{YYYYMMDD}/{category_id}/{uuid}.bmp` |
| 特征模板 | `templates/{YYYYMMDD}/{uuid}.{suffix}` |

MinIO 下同样是相对路径对象键，前缀不变。

## ISO 解码参数

对齐样本标定（decodeISOV1.1）：

- `setlen` 默认 **0**
- `setang` 默认 **256**

按 `fingerprint_layer_type` 可为每种特征类型单独配置。

## 界面

- 左侧：业务样本树（`dataset_code` → `cap_image_id`）
- 右侧：单栏 canvas + 特征层勾选；右侧第二栏为「配对栏（预留）」
- 导入 zip 时填写 `algo_version`；开启写回后刷新树可见新样本
- 管理员「特征类型」可增删启用类型
- **重复文件检测**（导入预检）：包内同内容、同名覆盖、左右同图、跨配对共用 bmp

## 重复文件检测

| 类型 | 含义 | 默认 | 严格模式 |
|------|------|------|----------|
| `zip_duplicate_content` | 包内多路径相同 SHA256 | 告警 | 告警 |
| `zip_name_collision` | zip 同名 / 大小写冲突（解压会覆盖） | 告警 | **中止** |
| `pair_same_bmp` | 同一对左右 bmp 内容相同 | 告警 | **中止** |
| `cross_pair_shared_bmp` | 不同配对目录共用同一 bmp 内容 | 告警 | 告警 |

另：bmp 已在图库（SHA256 命中）时仍**复用** `ImageInfo`，并在任务里统计 `library_bmp_reused`。

## 机器 A 上线

1. 拉取本分支并重启 backend / web
2. 表会自动创建，或执行 `sql/fingerprint_pairs.sql`
3. 打开「指纹对比」→ 选业务库连接 →（导入 zip 并启用路径写回）→ 点选样本浏览

环境变量 `FP_IMPORT_WORKERS`（默认 4）控制同时导入几对。

## API 摘要（业务浏览）

连接参数：`connection_id` + `database=ara_fp_analyst`（或测试用 `db_alias=default`）。

| 方法 | 路径 | 作用 |
|------|------|------|
| GET | `/api/fingerprints/biz/meta/` | `dataset_codes` + layer-types |
| GET | `/api/fingerprints/biz/samples/` | 分页列表（`dataset_code`、`keyword`） |
| GET | `/api/fingerprints/biz/samples/{cap_image_id}/view/` | `panels[]` 单栏载荷 |

View 响应形态：

```json
{
  "mode": "single",
  "panels": [
    {
      "role": "primary",
      "cap_image_id": "...",
      "dataset_code": "PK_5W",
      "image": { "path": "upload/...", "url": "", "error": null },
      "layers": [
        { "layer_type": "bidiso", "template_path": "templates/...", "minutiae": {}, "color": "...", "error": null }
      ]
    }
  ],
  "pair_meta": null
}
```

## 兼容 API（导入 / 旧配对）

- `GET /api/fingerprints/layer-types/` — 动态勾选配置
- `POST /api/fingerprints/layer-types/` — 管理员新增特征类型
- `PATCH /api/fingerprints/layer-types/{id}/` — 管理员更新
- `POST /api/fingerprints/pairs/import-zip/` — 导入 zip（可选 `path_writeback`）
- `GET /api/fingerprints/import-jobs/{id}/` — 任务进度
- `GET /api/fingerprints/pairs/` — 旧配对列表（仍可用，UI 已切到 biz）
- `GET /api/fingerprints/pairs/{id}/compare/` — 旧配对对比

## 路径写回（浏览数据源）

导入 batmatch zip 时可开启「路径写回」。目标固定为业务库：

| 目标 | 写入 |
|------|------|
| `ara_fp_analyst.T_CAP_FP_DATA` | `cap_image_id`=bmp stem；`dataset_code`=**`PK_5W`**；`fingerprint_image`=相对路径 `upload/...`（utf8 写入 longblob）；同时写入 `fingerprint_url` |
| `ara_fp_analyst.T_FEATURE_RECORD` | `fp_image_id`=`cap_image_id`；`fp_feature_id`=32 位 hex；Bidiso→`feature_ara_data`；Neuiso→`feature_neuro_data` |

说明：

1. 仍先写 MinIO + 本系统 `image_info` / `fingerprint_*`
2. 导入对话框只需选择能访问 `ara_fp_analyst` 的数据库连接
3. `feature_ara_data` / `feature_neuro_data` 原为 int 分数字段，首次写回时会自动 `ALTER` 为 `varchar(500)`
4. 同一 `cap_image_id` 再次导入会更新路径，不重复插主键冲突行

```json
{
  "enabled": true,
  "connection_id": 3,
  "database": "ara_fp_analyst",
  "dataset_code": "PK_5W"
}
```

## 扩展特征类型

管理员可增删 `fingerprint_layer_type`；业务浏览当前硬映射两列：

- `feature_ara_data` → `bidiso`
- `feature_neuro_data` → `neuiso`

## 非目标（本期不做）

配对关联表与双栏对比接线、bmp→模板提取引擎、删除 `fingerprint_pair` 导入路径、通用任意表浏览。
