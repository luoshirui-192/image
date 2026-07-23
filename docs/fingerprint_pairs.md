# 指纹配对对比（业务表驱动）

机器 A 部署本分支后即可使用「指纹对比」菜单。

## 主线流程（本期）

```text
t_match_result_image
  image_reg / image_match  (= bmp stem，与写回一致)
       │
       ├─► T_CAP_FP_DATA.cap_image_id     → 图路径 fingerprint_image
       └─► T_FEATURE_RECORD.fp_image_id   → Bidiso / Neuiso 路径
              → ISO 解码 → 双栏叠加
```

筛选留意：`t_match_result_image.data_set_code`（与 `T_CAP_FP_DATA.dataset_code` 对应，如 `PK_5W`）。

**本期不做：** 分数 / `sameflag` / 各 `*ms` 等指标展示与评测计算。

## 功能

1. 导入 batmatch zip（可选路径写回 `T_CAP_FP_DATA` + `T_FEATURE_RECORD`）
2. 左侧树：按 `data_set_code` 分组的配对（来自 `t_match_result_image`）
3. 右侧双栏：注册(`image_reg`) / 比对(`image_match`) 细节点叠加
4. 方向键切换上一对 / 下一对

## API（业务浏览）

| 方法 | 路径 | 作用 |
|------|------|------|
| GET | `/api/fingerprints/biz/meta/` | `data_set_code` 列表 + layer-types |
| GET | `/api/fingerprints/biz/pairs/` | 配对分页（`dataset_code`/`keyword`） |
| GET | `/api/fingerprints/biz/pairs/{id}/view/` | `mode=pair`，`panels[reg,match]` |

`pair_meta` 仅含：`id`、`image_reg`、`image_match`、`data_set_code`（不含 score 等指标）。

单样本兼容接口仍保留：`/biz/samples/`、`/biz/samples/{cap}/view/`。

## 路径写回

导入写回后两侧 stem 须能在 `T_CAP_FP_DATA` 命中，配对行才能双栏出图。

| 目标 | 写入 |
|------|------|
| `T_CAP_FP_DATA` | `cap_image_id`=stem；`dataset_code`=`PK_5W`；路径→`fingerprint_image` |
| `T_FEATURE_RECORD` | `fp_image_id`=stem；Bidiso→`feature_ara_data`；Neuiso→`feature_neuro_data` |

## 存储 / ISO

| 类型 | 路径 |
|------|------|
| 指纹 bmp | `upload/{YYYYMMDD}/{category_id}/{uuid}.bmp` |
| 特征模板 | `templates/{YYYYMMDD}/{uuid}.{suffix}` |

ISO：`setlen=0`，`setang=256`（可按 layer-type 配置）。

## 非本期

- 指标展示（score / sameflag / *ms）
- EER/FMR 报表
- 删除旧 `fingerprint_pair` 导入旁路
