import base64
import os
import unittest
from unittest.mock import patch

from src.core.llm.base_provider import BaseProvider
from src.core.llm.interfaces import CapabilityType
from src.core.llm.response import GenerateResult, StreamChunk, UsageInfo
from src.core.markdown_parser import (
    ElementType,
    ImageDescriber,
    MarkdownEnhancementOrchestrator,
    MarkdownParser,
    ProviderTableClient,
    ProviderVisionClient,
    TableClient,
    TableDescriber,
    VisionClient,
)


class MockVisionClient(VisionClient):
    def describe_images(self, urls, source_file=None):
        results = {}
        for url in urls:
            if "logo.jpg" in url:
                results[url] = "一个极简设计的蓝色科技公司 Logo。"
            elif "mountain.png" in url:
                results[url] = "一座被夕阳照亮的雪山风景图。"
        return results


class MockTableClient(TableClient):
    def describe_tables(self, tables, source_file=None):
        results = {}
        for table in tables:
            if "乔布斯" in table:
                results[table] = "该表格展示了乔布斯与林纳斯的技术栈和职级对比，林纳斯职级更高。"
        return results


class FakeTextProvider(BaseProvider):
    def __init__(self):
        super().__init__(provider_type="fake-text", provider_name="fake-text", api_key="")
        self._capabilities = {CapabilityType.TEXT}
        self.prompts = []

    async def generate(self, prompt, system_prompt=None, temperature=0.7, max_tokens=None, **kwargs):
        self.prompts.append(prompt)
        return GenerateResult(
            content='```text\n该表格反映了两位成员的部门与得分，张三得分最高。\n```',
            model="fake-text-model",
            usage=UsageInfo(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            provider_type=self.provider_type,
            latency_ms=1,
        )

    async def stream(self, prompt, system_prompt=None, temperature=0.7, max_tokens=None, **kwargs):
        yield StreamChunk(delta="", content="", is_end=True)


class FakeVisionProvider(BaseProvider):
    def __init__(self):
        super().__init__(provider_type="fake-vision", provider_name="fake-vision", api_key="")
        self._capabilities = {CapabilityType.VISION}
        self.calls = []

    async def generate(self, prompt, system_prompt=None, temperature=0.7, max_tokens=None, **kwargs):
        raise NotImplementedError

    async def stream(self, prompt, system_prompt=None, temperature=0.7, max_tokens=None, **kwargs):
        yield StreamChunk(delta="", content="", is_end=True)

    async def analyze_image(self, image_base64, prompt, **kwargs):
        self.calls.append((image_base64, prompt))
        return GenerateResult(
            content='"图片展示了一枚简洁的测试图标。"\n',
            model="fake-vision-model",
            usage=UsageInfo(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            provider_type=self.provider_type,
            latency_ms=1,
        )


class AsyncMockTableClient(TableClient):
    async def adescribe_tables(self, tables, source_file=None):
        return {table: "异步表格总结" for table in tables}


class AsyncMockVisionClient(VisionClient):
    async def adescribe_images(self, image_urls, source_file=None):
        return {image_url: "异步图片描述" for image_url in image_urls}


class TestMarkdownParserPipeline(unittest.TestCase):
    def setUp(self):
        self.parser = MarkdownParser()
        self.vision_client = MockVisionClient()
        self.table_client = MockTableClient()
        self.test_file = os.path.join(os.path.dirname(__file__), "test_pipeline_document.md")

    def test_full_pipeline(self):
        parse_result = self.parser.parse_file(self.test_file)

        element_types = [element.type for element in parse_result.elements]
        self.assertIn(ElementType.FRONT_MATTER, element_types)
        self.assertIn(ElementType.HEADING, element_types)
        self.assertIn(ElementType.PARAGRAPH, element_types)
        self.assertIn(ElementType.IMAGE, element_types)
        self.assertIn(ElementType.BLOCKQUOTE, element_types)
        self.assertIn(ElementType.LIST, element_types)
        self.assertIn(ElementType.CODE_BLOCK, element_types)
        self.assertIn(ElementType.MATH_BLOCK, element_types)
        self.assertIn(ElementType.TABLE, element_types)
        self.assertIn(ElementType.HORIZONTAL_RULE, element_types)

        self.assertEqual(len(parse_result.tables), 1)
        self.assertIn("乔布斯", parse_result.tables[0].content)
        self.assertEqual(len(parse_result.images), 2)

        parse_result = TableDescriber(self.table_client).process(parse_result)
        parse_result = ImageDescriber(self.vision_client).process(parse_result)

        found_inline_img_desc = False
        found_block_img_desc = False
        found_table_desc = False

        for element in parse_result.elements:
            if element.type == ElementType.PARAGRAPH and "logo.jpg" in element.content:
                self.assertIn("视觉描述: 一个极简设计的蓝色科技公司 Logo。", element.content)
                found_inline_img_desc = True

            if element.type == ElementType.IMAGE and "mountain.png" in element.content:
                self.assertIn("视觉描述: 一座被夕阳照亮的雪山风景图。", element.content)
                found_block_img_desc = True

            if element.type == ElementType.TABLE and "乔布斯" in element.content:
                self.assertIn(
                    "表格总结: 该表格展示了乔布斯与林纳斯的技术栈和职级对比，林纳斯职级更高。",
                    element.content,
                )
                found_table_desc = True

        self.assertTrue(found_inline_img_desc)
        self.assertTrue(found_block_img_desc)
        self.assertTrue(found_table_desc)


class TestProviderBackedClients(unittest.IsolatedAsyncioTestCase):
    async def test_provider_table_client_returns_raw_table_as_key(self):
        provider = FakeTextProvider()
        client = ProviderTableClient(provider=provider)
        table = (
            "| 姓名 | 部门 | 得分 |\n"
            "| --- | --- | --- |\n"
            "| 张三 | 算法 | 92 |\n"
            "| 李四 | 平台 | 88 |"
        )

        result = await client.adescribe_tables([table], source_file="docs/example.md")

        self.assertEqual(list(result.keys()), [table])
        self.assertEqual(result[table], "该表格反映了两位成员的部门与得分，张三得分最高。")
        self.assertEqual(len(provider.prompts), 1)
        self.assertIn("docs/example.md", provider.prompts[0])
        self.assertIn(table, provider.prompts[0])

    async def test_provider_vision_client_supports_data_url(self):
        provider = FakeVisionProvider()
        client = ProviderVisionClient(provider=provider, model_name="fake-vl-model")
        image_bytes = b"fake-image-binary"
        image_url = f"data:image/png;base64,{base64.b64encode(image_bytes).decode('utf-8')}"

        result = await client.adescribe_images([image_url], source_file="docs/example.md")

        self.assertEqual(result[image_url], "图片展示了一枚简洁的测试图标。")
        self.assertEqual(len(provider.calls), 1)
        sent_image_base64, sent_prompt = provider.calls[0]
        self.assertEqual(base64.b64decode(sent_image_base64), image_bytes)
        self.assertIn("docs/example.md", sent_prompt)


class TestAsyncOrchestration(unittest.IsolatedAsyncioTestCase):
    async def test_async_describers_merge_content(self):
        parser = MarkdownParser()
        parse_result = parser.parse_file(
            os.path.join(os.path.dirname(__file__), "test_pipeline_document.md")
        )

        parse_result = await TableDescriber(AsyncMockTableClient()).aprocess(parse_result)
        parse_result = await ImageDescriber(AsyncMockVisionClient()).aprocess(parse_result)
        markdown = parse_result.to_markdown()

        self.assertIn("[表格总结: 异步表格总结]", markdown)
        self.assertIn("[视觉描述: 异步图片描述]", markdown)

    async def test_orchestrator_triggers_enhancement_after_parse(self):
        markdown = (
            "# 示例\n\n"
            "| 姓名 | 部门 |\n"
            "| --- | --- |\n"
            "| 张三 | 算法 |\n\n"
            "![图](data:image/png;base64,ZmFrZQ==)"
        )
        orchestrator = MarkdownEnhancementOrchestrator()

        with patch(
            "src.core.markdown_parser.orchestrator.build_default_table_client",
            return_value=AsyncMockTableClient(),
        ), patch(
            "src.core.markdown_parser.orchestrator.build_default_vision_client",
            return_value=AsyncMockVisionClient(),
        ):
            enhanced = await orchestrator.aenhance_markdown(markdown, source_file="docs/example.md")

        self.assertIn("[表格总结: 异步表格总结]", enhanced)
        self.assertIn("[视觉描述: 异步图片描述]", enhanced)


if __name__ == "__main__":
    unittest.main(verbosity=2)
