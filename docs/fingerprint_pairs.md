# 指纹成对对比（Fingerprint Pair Compare）

机器 A 部署本分支后即可使用「指纹对比」菜单。

## 功能

1. 导入 batmatch_out 风格 zip（每对目录含 2 张 bmp + 各侧多层模板）
2. 按指位 / 批次 / 分数 / 特征类型 / 算法版本筛选配对
3. 对比页左右双栏，勾选 Bidiso / neuiso（及后续扩展类型）即时叠加细节点
4. 同算法多 `algo_version` 用不同颜色区分

## 存储

| 类型 | 路径 |
|------|------|
| 指纹 bmp | `upload/{YYYYMMDD}/{category_id}/{uuid}.bmp`（沿用现有） |
| 特征模板 | `templates/{YYYYMMDD}/{uuid}.{suffix}`（独立目录） |

MinIO 下同样是相对路径对象键，前缀不变。

## ISO 解码参数

对齐样本标定（decodeISOV1.1）：

- `setlen` 默认 **0**
- `setang` 默认 **256**

按 `fingerprint_layer_type` 可为每种特征类型单独配置。

## 成对筛选（已实现）

列表/左侧树通过 `GET /api/fingerprints/pairs/` 查询，支持：

| 参数 | 作用 |
|------|------|
| `finger_position` | 指位，如 `right_ring` |
| `batch_name` | 批次目录名模糊匹配 |
| `score_min` / `score_max` | 匹配分数区间 |
| `layer_type` | 是否含某特征层（bidiso/neuiso/…） |
| `algo_version` | 算法版本 |
| `keyword` | 人名 ID / 文件名 / 批次 / 标签 |

导入时已按 batmatch 目录解析成「一对」写入 `fingerprint_pair`，筛选作用在这对记录上，不是单张图。

## 界面

- 左侧：按指位分组的树 + 筛选条件
- 右侧：选中后即时双栏对比（不跳转新页）
- 每侧图片下方独立勾选特征层
- 版本对比：**叠色**（同图多 version 不同色）或 **分列**（同图左右两列各一 version）
- 导入 zip 时填写 `algo_version`；同一配对再导新版本会**合并特征层**（相同版本跳过）
- 管理员「特征类型」可增删启用类型（扩到约 6 种只加配置）
- **重复文件检测**（导入预检）：包内同内容、同名覆盖、左右同图、跨配对共用 bmp；默认告警仍导入，可选「严格模式」中止；进度区可展开明细

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
3. 打开「指纹对比」→ 导入 zip → 左侧树点选配对即可对比

环境变量 `FP_IMPORT_WORKERS`（默认 4）控制同时导入几对。

## API 摘要

- `GET /api/fingerprints/layer-types/` — 动态勾选配置
- `POST /api/fingerprints/layer-types/` — 管理员新增特征类型
- `PATCH /api/fingerprints/layer-types/{id}/` — 管理员更新（启用/颜色/解码参数等）
- `POST /api/fingerprints/pairs/import-zip/` — 导入 zip（`algo_version`；`fail_on_duplicates=1` 严格模式；同配对新版本合并层；可选 `path_writeback`）
- `GET /api/fingerprints/import-jobs/{id}/` — 任务进度，含 `duplicate_report`；启用写回时含 `writeback_updated` / `writeback_skipped` / `writeback_failed`
- `GET /api/fingerprints/pairs/` — 列表筛选
- `GET /api/fingerprints/pairs/{id}/compare/` — 对比数据（含 `available_algo_versions` / 各层 `color`）

## 路径写回（可选）

导入 batmatch zip 时，可在界面开启「路径写回」，或在 `path_writeback` 字段传入 JSON。行为：

1. 仍按原流程写入 MinIO + `image_info` / `fingerprint_*`
2. 额外对业务表执行 `UPDATE`，只填**相对路径字符串**（`upload/...`、`templates/...`）
3. 行匹配固定为：bmp 文件名中的 **personId + 指位**（如 `100001_right_index.bmp` → `person_id=100001` 且 `finger=right_index`）
4. 匹配不到的行记为跳过，不中止整包导入

示例：

```json
{
  "enabled": true,
  "connection_id": 3,
  "database": "biz_db",
  "table": "person_finger",
  "match": {
    "person_id_column": "person_id",
    "finger_column": "finger_code"
  },
  "paths": {
    "image_column": "image_path",
    "templates": {
      "bidiso": "bidiso_path",
      "neuiso": "neuiso_path"
    }
  }
}
```

也可用 `db_alias`（如 `default`）代替 `connection_id`。未映射的模板后缀不会写回。

## 扩展特征类型

管理员调用：

```json
POST /api/fingerprints/layer-types/
{
  "layer_key": "newtype",
  "label": "NewType",
  "color": "#43a047",
  "suffixes": "newtype",
  "default_setlen": 0,
  "default_setang": 256
}
```

导入带 `.newtype` 后缀的模板后，对比页勾选框会自动出现。

## 非目标（本期不做）

bmp→模板提取引擎、Neurotec/ISOTemplateView 集成、嵌入式固件；通用批量上传到任意表；INSERT 新业务行；zip 清单映射。
