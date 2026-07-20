"""Fingerprint pair APIs."""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from fingerprints.job_service import (
    cancel_import_job,
    create_import_job,
    kick_import_job_async,
    save_upload_to_staging,
    serialize_import_job,
)
from fingerprints.layer_config import list_layer_types, seed_default_layer_types
from fingerprints.models import FingerprintFeatureLayer, FingerprintImportJob, FingerprintLayerType, FingerprintPair
from fingerprints.services import (
    FingerprintImportError,
    build_compare_payload,
    import_from_uploaded_files,
    list_pairs,
    serialize_pair,
)
from utils.db_time import fetch_db_now
from utils.permissions import IsActiveAccount
from utils.responses import error_response, success_response


def _username(request) -> str:
    user = getattr(request, "user", None)
    return getattr(user, "username", "") or "anonymous"


class FingerprintLayerTypeListCreateView(APIView):
    """GET/POST /api/fingerprints/layer-types/"""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request):
        enabled_only = str(request.query_params.get("enabled_only", "1")).lower() not in {
            "0",
            "false",
            "no",
        }
        items = [info.to_dict() for info in list_layer_types(enabled_only=enabled_only)]
        return success_response({"items": items})

    def post(self, request):
        user = request.user
        if getattr(user, "role", "") != "admin":
            return error_response("仅管理员可新增特征类型", code=4031, status=403)

        data = request.data if isinstance(request.data, dict) else {}
        layer_key = str(data.get("layer_key") or "").strip().lower()
        if not layer_key:
            return error_response("layer_key 必填", code=4001, status=400)
        if FingerprintLayerType.objects.filter(layer_key=layer_key).exists():
            return error_response("layer_key 已存在", code=4006, status=409)

        suffixes = data.get("suffixes") or layer_key
        if isinstance(suffixes, list):
            suffixes = ",".join(str(s).strip().lower() for s in suffixes if str(s).strip())
        else:
            suffixes = str(suffixes).strip().lower()

        FingerprintLayerType.objects.create(
            layer_key=layer_key,
            label=str(data.get("label") or layer_key),
            color=str(data.get("color") or "#888888"),
            suffixes=suffixes,
            default_algo_name=str(data.get("default_algo_name") or layer_key),
            default_setlen=int(data.get("default_setlen", 0)),
            default_setang=int(data.get("default_setang", 256)),
            sort_order=int(data.get("sort_order", 100)),
            enabled=1 if data.get("enabled", True) else 0,
            create_time=fetch_db_now(),
        )
        from fingerprints.layer_config import get_layer_type

        info = get_layer_type(layer_key)
        return success_response(info.to_dict() if info else {"layer_key": layer_key}, message="created", status=201)


class FingerprintLayerTypeDetailView(APIView):
    """PATCH /api/fingerprints/layer-types/{id}/ — update type (admin)."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def patch(self, request, pk: int):
        if getattr(request.user, "role", "") != "admin":
            return error_response("仅管理员可修改特征类型", code=4031, status=403)

        row = FingerprintLayerType.objects.filter(id=pk).first()
        if not row:
            return error_response("特征类型不存在", code=4041, status=404)

        data = request.data if isinstance(request.data, dict) else {}
        if "label" in data:
            row.label = str(data.get("label") or row.layer_key)[:100]
        if "color" in data:
            row.color = str(data.get("color") or "#888888")[:20]
        if "suffixes" in data:
            suffixes = data.get("suffixes")
            if isinstance(suffixes, list):
                suffixes = ",".join(str(s).strip().lower() for s in suffixes if str(s).strip())
            else:
                suffixes = str(suffixes or "").strip().lower()
            if not suffixes:
                return error_response("suffixes 不能为空", code=4001, status=400)
            row.suffixes = suffixes[:200]
        if "default_algo_name" in data:
            row.default_algo_name = str(data.get("default_algo_name") or row.layer_key)[:100]
        if "default_setlen" in data:
            row.default_setlen = int(data.get("default_setlen"))
        if "default_setang" in data:
            row.default_setang = int(data.get("default_setang"))
        if "sort_order" in data:
            row.sort_order = int(data.get("sort_order"))
        if "enabled" in data:
            row.enabled = 1 if data.get("enabled") else 0
        row.save()

        from fingerprints.layer_config import get_layer_type

        info = get_layer_type(row.layer_key)
        return success_response(info.to_dict() if info else {"id": row.id})


class FingerprintPairListView(APIView):
    """GET /api/fingerprints/pairs/"""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request):
        seed_default_layer_types()
        params = request.query_params

        def _float(name: str):
            raw = params.get(name)
            if raw in (None, ""):
                return None
            try:
                return float(raw)
            except ValueError:
                return None

        def _int(name: str, default: int):
            try:
                return int(params.get(name, default))
            except (TypeError, ValueError):
                return default

        data = list_pairs(
            finger_position=(params.get("finger_position") or "").strip() or None,
            batch_name=(params.get("batch_name") or "").strip() or None,
            score_min=_float("score_min"),
            score_max=_float("score_max"),
            layer_type=(params.get("layer_type") or "").strip() or None,
            algo_version=(params.get("algo_version") or "").strip() or None,
            keyword=(params.get("keyword") or "").strip() or None,
            page=_int("page", 1),
            page_size=_int("page_size", 20),
        )
        return success_response(data)


class FingerprintPairImportZipView(APIView):
    """POST /api/fingerprints/pairs/import-zip/ — start background zip import job."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def post(self, request):
        upload = request.FILES.get("file") or request.FILES.get("zip")
        if not upload:
            return error_response("请上传 zip 文件 (file)", code=4001, status=400)

        tags = str(request.data.get("tags") or "fingerprint")
        algo_version = str(request.data.get("algo_version") or "1.0")
        skip_existing = str(request.data.get("skip_existing", "1")).lower() not in {
            "0",
            "false",
            "no",
        }
        category_id = request.data.get("category_id")
        try:
            category_id = int(category_id) if category_id not in (None, "") else None
        except (TypeError, ValueError):
            category_id = None

        try:
            zip_path = save_upload_to_staging(upload, filename=getattr(upload, "name", "upload.zip"))
            job = create_import_job(
                zip_path=str(zip_path),
                zip_name=getattr(upload, "name", zip_path.name),
                created_by=_username(request),
                algo_version=algo_version,
                tags=tags,
                skip_existing=skip_existing,
                category_id=category_id,
            )
            kick_import_job_async(job.id)
        except Exception as exc:
            return error_response(f"创建导入任务失败: {exc}", code=1, status=500)

        job = FingerprintImportJob.objects.get(pk=job.id)
        return success_response(
            {"job": serialize_import_job(job), "async": True},
            message="导入任务已启动",
            status=202,
        )


class FingerprintImportJobListView(APIView):
    """GET /api/fingerprints/import-jobs/"""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request):
        limit = 20
        try:
            limit = min(100, max(1, int(request.query_params.get("limit", 20))))
        except (TypeError, ValueError):
            pass
        rows = list(FingerprintImportJob.objects.all().order_by("-id")[:limit])
        return success_response({"items": [serialize_import_job(row) for row in rows]})


class FingerprintImportJobDetailView(APIView):
    """GET/POST /api/fingerprints/import-jobs/{id}/  POST action=cancel"""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request, pk: int):
        job = FingerprintImportJob.objects.filter(id=pk).first()
        if not job:
            return error_response("导入任务不存在", code=4041, status=404)
        return success_response(serialize_import_job(job))

    def post(self, request, pk: int):
        action = str(request.data.get("action") or "").strip().lower()
        if action != "cancel":
            return error_response("仅支持 action=cancel", code=4001, status=400)
        try:
            job = cancel_import_job(pk)
        except FingerprintImportError as exc:
            return error_response(str(exc), code=4041, status=404)
        return success_response(serialize_import_job(job), message="cancel requested")


class FingerprintPairImportFilesView(APIView):
    """POST /api/fingerprints/pairs/import/ — multipart one pair (bmp + templates)."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def post(self, request):
        uploads = request.FILES.getlist("files") or request.FILES.getlist("file")
        if not uploads:
            return error_response("请上传成对 bmp 与模板文件 (files)", code=4001, status=400)

        files = [(f.name, f.read()) for f in uploads]
        tags = str(request.data.get("tags") or "fingerprint")
        algo_version = str(request.data.get("algo_version") or "1.0")
        batch_name = str(request.data.get("batch_name") or "").strip()
        score_raw = request.data.get("match_score")
        match_score = None
        if score_raw not in (None, ""):
            try:
                match_score = float(score_raw)
            except (TypeError, ValueError):
                return error_response("match_score 无效", code=4001, status=400)

        category_id = request.data.get("category_id")
        try:
            category_id = int(category_id) if category_id not in (None, "") else None
        except (TypeError, ValueError):
            category_id = None

        try:
            result = import_from_uploaded_files(
                files,
                upload_user=_username(request),
                batch_name=batch_name,
                match_score=match_score,
                tags=tags,
                algo_version=algo_version,
                category_id=category_id,
            )
        except FingerprintImportError as exc:
            return error_response(str(exc), code=4001, status=400)

        return success_response(
            {
                "pair_id": result.pair_id,
                "batch_name": result.batch_name,
                "finger_position": result.finger_position,
                "layer_count": result.layer_count,
            },
            status=201,
        )


class FingerprintPairDetailView(APIView):
    """GET/DELETE /api/fingerprints/pairs/{id}/"""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request, pk: int):
        pair = FingerprintPair.objects.filter(id=pk, is_delete=0).first()
        if not pair:
            return error_response("配对不存在", code=4041, status=404)
        return success_response(serialize_pair(pair, include_layers=True))

    def delete(self, request, pk: int):
        pair = FingerprintPair.objects.filter(id=pk, is_delete=0).first()
        if not pair:
            return error_response("配对不存在", code=4041, status=404)
        pair.is_delete = 1
        pair.update_time = fetch_db_now()
        pair.save(update_fields=["is_delete", "update_time"])
        return success_response({"id": pk}, message="deleted")


class FingerprintPairCompareView(APIView):
    """GET /api/fingerprints/pairs/{id}/compare/"""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request, pk: int):
        layers_param = request.query_params.get("layers")
        if layers_param is None:
            layers_param = request.query_params.get("layer_types")
        versions_param = request.query_params.get("versions")
        if versions_param is None:
            versions_param = request.query_params.get("algo_versions")

        selected_layers = None
        if layers_param is not None:
            selected_layers = [x.strip() for x in layers_param.split(",") if x.strip()]
        selected_versions = None
        if versions_param is not None:
            selected_versions = [x.strip() for x in versions_param.split(",") if x.strip()]

        show_labels = str(request.query_params.get("show_labels", "1")).lower() not in {
            "0",
            "false",
            "no",
        }
        try:
            payload = build_compare_payload(
                pk,
                selected_layer_types=selected_layers,
                selected_versions=selected_versions,
                show_labels=show_labels,
            )
        except FingerprintImportError as exc:
            return error_response(str(exc), code=4041, status=404)
        return success_response(payload)


class FingerprintMetaView(APIView):
    """GET /api/fingerprints/meta/ — filter options."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request):
        seed_default_layer_types()
        positions = (
            FingerprintPair.objects.filter(is_delete=0)
            .exclude(finger_position="")
            .values_list("finger_position", flat=True)
            .distinct()
        )
        versions = (
            FingerprintFeatureLayer.objects.values_list("algo_version", flat=True).distinct()
        )
        return success_response(
            {
                "finger_positions": sorted(set(positions)),
                "algo_versions": sorted(set(versions)),
                "layer_types": [info.to_dict() for info in list_layer_types(enabled_only=True)],
            }
        )
