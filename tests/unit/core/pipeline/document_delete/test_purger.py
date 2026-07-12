"""DocumentDeletePurger 编排单测（LINK-55）。

用注入的 fake 替代各存储依赖、monkeypatch get_db_context，验证：
- 删除次序：外部存储（Qdrant/ES/OSS）全部先于 DB 行删除；
- 非规范 key 护栏（兜底）：parsed_object_key 非 parsed/ 前缀被跳过，绝不误删原文件；
- taskId 目录前缀：md + 图片整目录一次删 + 去重；
- dataset 分页枚举逐文件清理、取空即止；
- 空产物（已删/未解析）全程 no-op。
"""

from contextlib import asynccontextmanager

from src.core.mq.messages import DocumentDeleteMessage
from src.core.pipeline.document_delete import purger as purger_module
from src.core.pipeline.document_delete.purger import DocumentDeletePurger
from src.core.storage.index_mutation_guard import NoopIndexMutationGuard


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class _FakeDB:
    def __init__(self, log):
        self._log = log

    async def commit(self):
        self._log.append("db.commit")


class _FakeDBCtx:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *exc):
        return False


class _FakeChunkRepo:
    def __init__(self, log, routing):
        self._log = log
        self._routing = routing

    async def list_routing_by_doc_id(self, db, doc_id, user_id):
        return list(self._routing.get(doc_id, []))

    async def delete_by_doc_id(self, db, doc_id):
        self._log.append(f"db.delete_chunks:{doc_id}")
        return 0


class _FakeParseRepo:
    def __init__(self, log, oss_keys, dataset_pages):
        self._log = log
        self._oss_keys = oss_keys
        self._dataset_pages = list(dataset_pages)

    async def list_doc_ids_by_dataset(self, db, dataset_id, user_id, *, limit):
        return self._dataset_pages.pop(0) if self._dataset_pages else []

    async def list_parsed_oss_keys_by_doc_id(self, db, doc_id):
        return list(self._oss_keys.get(doc_id, []))

    async def delete_parse_rows_by_doc_id(self, db, doc_id):
        self._log.append(f"db.delete_parse_rows:{doc_id}")
        return {}


class _FakeQdrant:
    def __init__(self, log):
        self._log = log
        self.calls = []

    async def delete_points(self, *, bucket_id, chunk_ids):
        self._log.append(f"qdrant.delete:{bucket_id}:{sorted(chunk_ids)}")
        self.calls.append((bucket_id, sorted(chunk_ids)))


class _FakeEs:
    def __init__(self, log):
        self._log = log
        self.calls = []

    async def delete_document_index(self, *, user_id, dataset_id, doc_id):
        self._log.append(f"es.delete:{doc_id}")
        self.calls.append((user_id, dataset_id, doc_id))
        return 0


class _FakeEsWithDatasetDrop(_FakeEs):
    """模拟 Manticore 后端：额外暴露 delete_by_dataset（ES/Qdrant 没有这个方法）。"""

    def __init__(self, log):
        super().__init__(log)
        self.dropped_datasets: list[tuple[int, int]] = []

    async def delete_by_dataset(self, *, user_id, dataset_id):
        self._log.append(f"es.drop_dataset:{dataset_id}")
        self.dropped_datasets.append((user_id, dataset_id))


class _FakeStorage:
    def __init__(self, log):
        self._log = log
        self.removed = []

    def remove_prefix(self, bucket, prefix):
        self._log.append(f"oss.remove:{bucket}:{prefix}")
        self.removed.append((bucket, prefix))
        return 0


def _make_purger(monkeypatch, *, routing=None, oss_keys=None, dataset_pages=None, es_cls=_FakeEs):
    log: list[str] = []
    db = _FakeDB(log)
    monkeypatch.setattr(purger_module, "get_db_context", lambda: _FakeDBCtx(db))
    chunk_repo = _FakeChunkRepo(log, routing or {})
    parse_repo = _FakeParseRepo(log, oss_keys or {}, dataset_pages or [])
    qdrant = _FakeQdrant(log)
    es = es_cls(log)
    storage = _FakeStorage(log)
    purger = DocumentDeletePurger(
        chunk_repository=chunk_repo,
        parse_repository=parse_repo,
        qdrant_store=qdrant,
        es_pipeline=es,
        storage=storage,
        page_size=10,
        mutation_guard=NoopIndexMutationGuard(),
    )
    return purger, log, qdrant, es, storage


# --------------------------------------------------------------------------- #
# _task_dir_prefixes（护栏 + 去重）
# --------------------------------------------------------------------------- #
class TestTaskDirPrefixes:
    def test_parsed_product_uses_parent_dir(self):
        keys = [("priv", "parsed/user-1/dataset-1/2026/06/20/abc/file.md")]
        out = DocumentDeletePurger._task_dir_prefixes(keys)
        assert out == [("parsed/user-1/dataset-1/2026/06/20/abc/", "priv")]

    def test_non_parsed_prefix_key_is_skipped(self):
        # 非规范 key（不在 parsed/ 根下，如异常数据指向原文件位置）→ 必须跳过，绝不误删原文件
        keys = [("priv", "user-1/dataset-1/file.md")]
        assert DocumentDeletePurger._task_dir_prefixes(keys) == []

    def test_dedup_same_task_dir(self):
        keys = [
            ("priv", "parsed/u/d/2026/06/20/abc/a.md"),
            ("priv", "parsed/u/d/2026/06/20/abc/a.md"),
        ]
        assert DocumentDeletePurger._task_dir_prefixes(keys) == [
            ("parsed/u/d/2026/06/20/abc/", "priv")
        ]

    def test_none_or_empty_skipped(self):
        keys = [(None, "parsed/x/y.md"), ("priv", None), ("", "")]
        assert DocumentDeletePurger._task_dir_prefixes(keys) == []

    def test_shallow_prefix_is_rejected_by_depth_guard(self):
        # 异常浅 key：parent 段数 < _MIN_TASK_DIR_SEGMENTS，必须拦掉，绝不下发宽前缀
        shallow = [
            ("priv", "parsed/x.md"),  # parent="parsed" (1 段)
            ("priv", "parsed/user-1/x.md"),  # parent="parsed/user-1" (2 段)
            ("priv", "parsed/user-1/dataset-1/x.md"),  # (3 段)
        ]
        assert DocumentDeletePurger._task_dir_prefixes(shallow) == []

    def test_canonical_depth_passes(self):
        # 规范 7 段父目录：parsed/user-1/dataset-1/2026/06/20/task → 通过
        keys = [("priv", "parsed/user-1/dataset-1/2026/06/20/task/f.md")]
        assert DocumentDeletePurger._task_dir_prefixes(keys) == [
            ("parsed/user-1/dataset-1/2026/06/20/task/", "priv")
        ]


# --------------------------------------------------------------------------- #
# 单文件编排
# --------------------------------------------------------------------------- #
class TestPurgeFile:
    async def test_acquires_all_branch_locks_in_fixed_order(self, monkeypatch):
        class _RecordingGuard:
            def __init__(self):
                self.events = []

            @asynccontextmanager
            async def hold(self, *, doc_id, branch, timeout_seconds=None):
                self.events.append(f"enter:{branch.value}:{doc_id}")
                try:
                    yield None
                finally:
                    self.events.append(f"exit:{branch.value}:{doc_id}")

        purger, log, _, _, _ = _make_purger(monkeypatch)
        guard = _RecordingGuard()
        purger._mutation_guard = guard
        payload = DocumentDeleteMessage.build(
            delete_type="file", dataset_id=2, user_id=1, original_file_id=7
        ).get_payload()

        await purger.purge(payload)

        assert guard.events == [
            "enter:DENSE:7",
            "enter:SPARSE:7",
            "enter:BM25:7",
            "exit:BM25:7",
            "exit:SPARSE:7",
            "exit:DENSE:7",
        ]
        # DB 销账位于锁的临界区内，而非释放后再删。
        assert "db.delete_parse_rows:7" in log

    async def test_external_stores_deleted_before_db_rows(self, monkeypatch):
        purger, log, qdrant, es, storage = _make_purger(
            monkeypatch,
            routing={7: [("c1", 3), ("c2", 3)]},
            oss_keys={7: [("priv", "parsed/u/d/2026/06/20/task7/f.md")]},
        )
        payload = DocumentDeleteMessage.build(
            delete_type="file", dataset_id=2, user_id=1, original_file_id=7
        ).get_payload()

        await purger.purge(payload)

        # 外部三类删除都发生
        assert qdrant.calls == [(3, ["c1", "c2"])]
        assert es.calls == [(1, 2, 7)]
        assert storage.removed == [("priv", "parsed/u/d/2026/06/20/task7/")]
        # 铁律：外部存储删除全部早于任意 DB 行删除
        last_external = max(
            i
            for i, e in enumerate(log)
            if e.startswith(("qdrant.delete", "es.delete", "oss.remove"))
        )
        first_db_delete = min(
            i
            for i, e in enumerate(log)
            if e.startswith(("db.delete_chunks", "db.delete_parse_rows"))
        )
        assert last_external < first_db_delete
        assert "db.commit" in log

    async def test_empty_products_is_noop(self, monkeypatch):
        # 已删/未解析：routing 与 oss 均空 → 不调外部删除，DB 删按 id 空删
        purger, log, qdrant, es, storage = _make_purger(monkeypatch)
        payload = DocumentDeleteMessage.build(
            delete_type="file", dataset_id=2, user_id=1, original_file_id=99
        ).get_payload()

        await purger.purge(payload)

        assert qdrant.calls == []
        assert storage.removed == []
        # ES 按 filter 删（无匹配返 0），仍会调用一次——幂等
        assert es.calls == [(1, 2, 99)]
        assert "db.delete_chunks:99" in log
        assert "db.delete_parse_rows:99" in log


# --------------------------------------------------------------------------- #
# 数据集编排（分页）
# --------------------------------------------------------------------------- #
class TestPurgeDataset:
    async def test_paginates_until_empty_and_purges_each(self, monkeypatch):
        purger, log, qdrant, es, storage = _make_purger(
            monkeypatch,
            dataset_pages=[[11, 12], [13], []],
        )
        payload = DocumentDeleteMessage.build(
            delete_type="dataset", dataset_id=5, user_id=1
        ).get_payload()

        await purger.purge(payload)

        deleted_docs = [e.split(":")[1] for e in log if e.startswith("db.delete_parse_rows:")]
        assert deleted_docs == ["11", "12", "13"]

    async def test_drops_dataset_table_when_pipeline_supports_it(self, monkeypatch):
        # Manticore 后端才有 delete_by_dataset；探测到就在逐文件清理完之后调用一次整表 DROP。
        purger, log, qdrant, es, storage = _make_purger(
            monkeypatch,
            dataset_pages=[[21], []],
            es_cls=_FakeEsWithDatasetDrop,
        )
        payload = DocumentDeleteMessage.build(
            delete_type="dataset", dataset_id=5, user_id=1
        ).get_payload()

        await purger.purge(payload)

        assert es.dropped_datasets == [(1, 5)]
        # 表级 DROP 必须发生在逐文件清理之后，而不是之前。
        last_file_delete = max(
            i for i, e in enumerate(log) if e.startswith("db.delete_parse_rows:")
        )
        drop_idx = next(i for i, e in enumerate(log) if e.startswith("es.drop_dataset:"))
        assert last_file_delete < drop_idx

    async def test_skips_dataset_drop_when_pipeline_lacks_method(self, monkeypatch):
        # ES/Qdrant 后端没有 delete_by_dataset，hasattr 探测不到即跳过，不应报错。
        purger, log, qdrant, es, storage = _make_purger(
            monkeypatch,
            dataset_pages=[[21], []],
        )
        payload = DocumentDeleteMessage.build(
            delete_type="dataset", dataset_id=5, user_id=1
        ).get_payload()

        await purger.purge(payload)

        assert not any(e.startswith("es.drop_dataset:") for e in log)
