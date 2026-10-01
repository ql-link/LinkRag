import Markdown from 'react-markdown';
import rehypeRaw from 'rehype-raw';
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize';
import remarkGfm from 'remark-gfm';

// MinerU 的表格可能为 HTML；保留合并单元格，其他 HTML 按白名单过滤。
const schema = {
  ...defaultSchema,
  attributes: {
    ...defaultSchema.attributes,
    td: [...(defaultSchema.attributes?.td ?? []), 'colSpan', 'rowSpan'],
    th: [...(defaultSchema.attributes?.th ?? []), 'colSpan', 'rowSpan'],
  },
};

/** 文档正文共用的 Markdown 阅读视图。 */
export function MarkdownBody({ children }: { children: string }) {
  return (
    <div className="document-markdown min-w-0">
      <Markdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw, [rehypeSanitize, schema]]}
        components={{
          table: ({ children }) => <div className="document-table-scroll"><table>{children}</table></div>,
          a: ({ children, href, title }) => <a href={href} title={title} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>{children}</a>,
          img: ({ src, alt, title }) => src ? <img src={src} alt={alt ?? ''} title={title} loading="lazy" /> : <span>{alt}</span>,
        }}
      >
        {children}
      </Markdown>
    </div>
  );
}
