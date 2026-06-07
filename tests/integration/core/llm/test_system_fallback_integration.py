import pytest
from src.services.config_reader_service import ConfigReaderService
from src.core.llm.factory import ModelFactory
from src.core.llm.interfaces import ITextGenerator, IEmbedder


@pytest.fixture
def config_service():
    # 测试兜底不需要真正的 DB 连接实例
    return ConfigReaderService(db=None)


@pytest.fixture
def factory():
    return ModelFactory()


@pytest.mark.asyncio
async def test_system_fallback_chat(config_service, factory):
    """测试系统兜底配置加载与 Qwen CHAT 调用"""
    config = config_service.get_system_fallback_config_by_capability("CHAT")

    assert config is not None, "兜底配置缺失，请检查环境变量(SYSTEM_LLM_API_KEY)"
    assert config["is_system_fallback"] is True
    assert config["capability"] == "CHAT"
    assert config["provider_type"] == "qwen"
    assert config["model_name"] == "qwen3.5-flash"

    if not config["api_key"] or config["api_key"] == "your_qwen_api_key_here":
        pytest.skip("检测到使用的是占位 API_KEY，跳过真实的网络请求阶段")

    # 创建并测试 Client
    client = factory.create_client(
        provider_type=config["provider_type"],
        api_key=config["api_key"],
        api_base_url=config["api_base_url"],
        model_name=config["model_name"],
    )

    # [真实网络请求] 发起生成调用
    print(f"\n>>> 发起 CHAT 请求 (Model: {config['model_name']})")
    result = await client.generate(prompt="你好，请只用 10 个字介绍你自己。")

    print(f"\n<<< 收到响应: {result.content}")
    print(f"<<< 用量统计: {result.usage}")
    assert result.content is not None
    assert result.usage.total_tokens > 0


@pytest.mark.asyncio
async def test_system_fallback_embedding(config_service, factory):
    """测试系统兜底配置加载与 Qwen EMBEDDING 调用"""
    config = config_service.get_system_fallback_config_by_capability("EMBEDDING")

    assert config is not None
    assert config["capability"] == "EMBEDDING"

    if not config["api_key"] or config["api_key"] == "your_qwen_api_key_here":
        pytest.skip("检测到使用的是占位 API_KEY，跳过真实的网络请求阶段")

    client = factory.create_client(
        provider_type=config["provider_type"],
        api_key=config["api_key"],
        api_base_url=config["api_base_url"],
        model_name=config["model_name"],
    )

    # [真实网络请求] 发起向量化调用
    print(f"\n>>> 发起 EMBEDDING 请求 (Model: {config['model_name']})")
    result = await client.embed(
        texts=["这是一个用于测试的自然语言问句，请转化为向量分布"], model=config["model_name"]
    )

    vectors = result.embeddings
    print(f"\n<<< 收到响应: 共 {len(vectors)} 条向量")
    print(f"<<< 向量唯度: {len(vectors[0])} d")
    print(f"<<< 用量统计: {result.usage}")

    assert len(vectors) == 1
    assert len(vectors[0]) > 0  # 例如通常是 1024, 1536 等
