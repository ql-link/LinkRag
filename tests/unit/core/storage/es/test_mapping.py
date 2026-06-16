from src.core.storage.es.mapping import build_es_index_body


class TestBuildEsIndexBody:
    def test_should_set_shards_and_replicas(self):
        body = build_es_index_body(shards=3, replicas=1)

        assert body["settings"]["number_of_shards"] == 3
        assert body["settings"]["number_of_replicas"] == 1

    def test_should_define_whitespace_lowercase_analyzers(self):
        analyzers = build_es_index_body(shards=1, replicas=0)["settings"]["analysis"]["analyzer"]

        for name in ("chunk_index_analyzer", "chunk_search_analyzer"):
            assert analyzers[name]["tokenizer"] == "whitespace"
            assert analyzers[name]["filter"] == ["lowercase"]

    def test_should_require_routing_and_exclude_token_source(self):
        mappings = build_es_index_body(shards=1, replicas=0)["mappings"]

        assert mappings["routing"] == {"required": True}
        assert mappings["_source"]["excludes"] == ["coarse_tokens", "fine_tokens"]

    def test_should_map_field_types(self):
        props = build_es_index_body(shards=1, replicas=0)["mappings"]["properties"]

        assert props["chunk_id"]["type"] == "keyword"
        assert props["user_id"]["type"] == "long"
        assert props["dataset_id"]["type"] == "long"
        assert props["doc_id"]["type"] == "long"
        assert props["task_id"]["type"] == "keyword"
        assert props["chunk_index"]["type"] == "integer"
        assert props["coarse_tokens"]["type"] == "text"
        assert props["coarse_tokens"]["store"] is False
        assert props["fine_tokens"]["type"] == "text"
