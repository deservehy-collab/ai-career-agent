/**
 * 模型输出的安全渲染：markdown **子集** → HTML。
 *
 * 为什么不用现成库：本次要求不新增依赖，而聊天只需要有限语法。
 * 更重要的是安全 —— 模型输出属于**不可信内容**，直接 v-html 会引入 XSS。
 *
 * 处理顺序保证安全：
 *   1. 先把整段文本里的 `& < > " '` 全部转义（任何标签都失效）；
 *   2. 再在转义后的文本上，只插入下面代码里白名单的几个标签
 *      （p / ul / ol / li / pre / code / strong / em / h4 / blockquote）；
 *   3. 不渲染链接、不渲染 img、不透传任何属性 —— 因此不存在 javascript: 注入面。
 *
 * 支持的语法：``` 代码块、`#` 到 `######` 标题（统一显示成小标题）、- 与 * 无序列表、1. 有序列表、
 * > 引用、`行内代码`、**加粗**、*斜体*、空行分段。其余原样显示。
 */

const ESCAPE_MAP = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
}

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) => ESCAPE_MAP[ch])
}

/** 行内语法。入参必须**已经转义**，否则不安全。 */
function renderInline(escaped) {
  return escaped
    .replace(/`([^`\n]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*\w])\*([^*\n]+)\*/g, '$1<em>$2</em>')
}

const UNORDERED = /^\s*[-*+]\s+(.*)$/
const ORDERED = /^\s*\d+[.)]\s+(.*)$/
const QUOTE = /^\s*>\s?(.*)$/
// 到 6 级：模型很爱用 ####，只认 1-3 级会让它变成一行字面 "#### xxx"。
// 一律渲染成 h4 —— 聊天面板里层级差别没意义，字号只差一档。
const HEADING = /^#{1,6}[ \t]+(.*)$/

/**
 * @param {string} source 模型原始文本（未转义）
 * @returns {string} 可以安全交给 v-html 的 HTML 片段
 */
export function renderMarkdown(source) {
  const lines = String(source ?? '').replace(/\r\n?/g, '\n').split('\n')
  const blocks = []

  let listTag = null
  let listItems = []
  let paragraph = []

  function flushList() {
    if (!listTag) return
    blocks.push(`<${listTag}>${listItems.join('')}</${listTag}>`)
    listTag = null
    listItems = []
  }

  function flushParagraph() {
    if (!paragraph.length) return
    blocks.push(`<p>${paragraph.map(renderInline).join('<br>')}</p>`)
    paragraph = []
  }

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]

    // 代码块：整段原样保留，只转义。未闭合也当代码块渲染 ——
    // 流式生成时模型常常正处于代码块中间，这样不会闪出半截标签。
    if (line.trim().startsWith('```')) {
      flushParagraph()
      flushList()
      const code = []
      index += 1
      while (index < lines.length && !lines[index].trim().startsWith('```')) {
        code.push(lines[index])
        index += 1
      }
      blocks.push(`<pre><code>${escapeHtml(code.join('\n'))}</code></pre>`)
      continue
    }

    if (!line.trim()) {
      flushParagraph()
      flushList()
      continue
    }

    const heading = line.match(HEADING)
    if (heading) {
      flushParagraph()
      flushList()
      blocks.push(`<h4 class="md-h">${renderInline(escapeHtml(heading[1]))}</h4>`)
      continue
    }

    const quote = line.match(QUOTE)
    if (quote) {
      flushParagraph()
      flushList()
      blocks.push(`<blockquote class="md-quote">${renderInline(escapeHtml(quote[1]))}</blockquote>`)
      continue
    }

    const ordered = line.match(ORDERED)
    const unordered = ordered ? null : line.match(UNORDERED)
    if (ordered || unordered) {
      flushParagraph()
      const wanted = ordered ? 'ol' : 'ul'
      if (listTag && listTag !== wanted) flushList()
      listTag = wanted
      listItems.push(`<li>${renderInline(escapeHtml((ordered || unordered)[1]))}</li>`)
      continue
    }

    flushList()
    paragraph.push(escapeHtml(line.trim()))
  }

  flushParagraph()
  flushList()
  return blocks.join('')
}
