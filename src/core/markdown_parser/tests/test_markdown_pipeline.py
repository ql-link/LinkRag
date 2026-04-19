import sys
import os
import unittest

# 配置环境变量，保证可以无缝导入工程上方的 src 层核心包
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from core.markdown_parser import (
    MarkdownParser,
    VisionClient,
    ImageDescriber,
    TableClient,
    TableDescriber,
    ElementType,
)
from typing import Dict, List

# ----- Mock 客户端，拟合现实生产环境大模型接口的行为 -----
class MockVisionClient(VisionClient):
    def describe_images(self, urls: List[str], source_file: str | None = None) -> Dict[str, str]:
        results = {}
        for url in urls:
            if "logo.jpg" in url:
                results[url] = "一个极简设计的蓝色科技公司Logo。"
            elif "mountain.png" in url:
                results[url] = "巍峨的雪山在金色夕阳的余晖下显得格外辉煌。"
        return results

class MockTableClient(TableClient):
    def describe_tables(self, tables: List[str], source_file: str | None = None) -> Dict[str, str]:
        results = {}
        for table in tables:
            if "乔布斯" in table:
                results[table] = "该表格展示了IT界两位传奇人物(乔布斯、林纳斯)的核心技术栈以及象征性的极高职级评估。"
        return results


class TestMarkdownParserPipeline(unittest.TestCase):
    def setUp(self):
        """初始化所有的管道与客户端组建"""
        self.parser = MarkdownParser()
        self.vision_client = MockVisionClient()
        self.table_client = MockTableClient()
        
        # 指向我们刚创建的巨型 Markdown 测试文件
        self.test_file = os.path.join(os.path.dirname(__file__), "test_pipeline_document.md")

    def test_full_pipeline(self):
        """核心测试：测试整个 Markdown 解析树扫描，及大模型定向定点原位增强"""
        # --- 阶段一：闪电解析（无网络） ---
        parse_result = self.parser.parse_file(self.test_file)
        
        # 【断言 1】所有语法都应该被识别成为相应的 ElementType
        element_types = [e.type for e in parse_result.elements]
        
        self.assertIn(ElementType.FRONT_MATTER, element_types, "丢失了文件开头的 YAML Front Matter")
        self.assertIn(ElementType.HEADING, element_types, "未识别出 # 和 ### 类型的标题")
        self.assertIn(ElementType.PARAGRAPH, element_types, "失去了普通的正文段落")
        self.assertIn(ElementType.IMAGE, element_types, "独立存在的图片行必须划为独立的 IMAGE 节点")
        self.assertIn(ElementType.BLOCKQUOTE, element_types, "块级引入 > 符号丢失")
        self.assertIn(ElementType.LIST, element_types, "包含数字或横杠的列表解析失败")
        self.assertIn(ElementType.CODE_BLOCK, element_types, "围栏式代码区解析失败")
        self.assertIn(ElementType.MATH_BLOCK, element_types, "缺少对应的块级公式节点解析")
        self.assertIn(ElementType.TABLE, element_types, "原生的 Markdown 表格被遗漏或者错划分")
        self.assertIn(ElementType.HORIZONTAL_RULE, element_types, "文档最后的水平线 --- 未被探测")

        # 【断言 2】Parser 抛出的旁挂件收集（为了外部统计或是发模型方便）
        self.assertEqual(len(parse_result.tables), 1, "应该精准提取出只有1个表格实体")
        self.assertIn("乔布斯", parse_result.tables[0].content)

        self.assertEqual(len(parse_result.images), 2, "内联1张+独立1张，总应该有2张图")

        # --- 阶段二：大模型定向注水（重型 I/O） ---
        parse_result = TableDescriber(self.table_client).process(parse_result)
        parse_result = ImageDescriber(self.vision_client).process(parse_result)

        # 【断言 3】大模型内容成功且正确地定点着陆
        found_inline_img_desc = False
        found_block_img_desc = False
        found_table_desc = False

        print("\n" + "="*70)
        print("全面端到端压力测试：Markdown 扫描与大模型组装日志回显")
        print("="*70)
        
        for idx, e in enumerate(parse_result.elements):
            # 将输出信息美化并且支持在控制台看缩进
            print(f"[{idx:02d}] {e.type.name.ljust(15)} (第 {e.start_line:02d}-{e.end_line:02d} 行)")
            lines = e.content.split("\n")
            for line in lines:
                print(f"    {line}")
            if e.metadata:
                print(f"    [Meta信息]: {e.metadata}")
            print("-" * 50)
            
            # --- 精确检验效果 ---
            if e.type == ElementType.PARAGRAPH and "logo.jpg" in e.content:
                self.assertIn("视觉描述: 一个极简设计的蓝色科技公司Logo。", e.content)
                found_inline_img_desc = True
                
            if e.type == ElementType.IMAGE and "mountain.png" in e.content:
                self.assertIn("视觉描述: 巍峨的雪山", e.content)
                found_block_img_desc = True
                
            if e.type == ElementType.TABLE and "乔布斯" in e.content:
                self.assertIn("表格总结: 该表格展示了IT界两位传奇人物", e.content)
                found_table_desc = True

        # 最后统计有没有被篡改漏发
        self.assertTrue(found_inline_img_desc, "重大缺陷：内联图片的描述未能成功追加在相关段落内！")
        self.assertTrue(found_block_img_desc, "重大缺陷：单行独立图片的描述未能成功上载！")
        self.assertTrue(found_table_desc, "重大缺陷：核心的表格说明未能在该原生 TABLE 节点末尾显现！")


if __name__ == '__main__':
    # 支持命令行下直观的终端色彩输出（如果你用支持的终端）
    unittest.main(verbosity=2)
