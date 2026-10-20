<script setup>
import { computed } from 'vue'

import { AGENTS, AGENT_GROUP } from '../utils/agents'

/**
 * 概览首页：产品的「导览页」，不是数据统计后台。
 *
 * 这页只回答使用者真正关心的三件事 —— 有什么能用、用来干什么、怎么用 ——
 * 然后把人送到对应页面去。因此：
 *
 * 1. **不展示任何运维数据**：不读 Ollama 状态、不数技能或项目条数，
 *    也不放「我的当前进度」这类读数。那些属于「系统状态」页，不在这。
 *    整页纯静态、不发任何请求。
 * 2. **只链真实路由**：AI 助手 /assistant、岗位分析 /analyze、
 *    学习与项目 /tasks、成长记录 /growth、系统状态 /status —— 都是确实存在的页面。
 * 3. **不编造事实**：文案来自 graph/workflow.py 的七节点与 utils/agents.js，
 *    流程与产出可追溯到真实节点。
 */

// ── 有什么能用：五个真实页面，各配一句「用来干什么」和一个去处 ──────────
const features = [
  {
    key: 'assistant',
    title: 'AI 助手',
    desc: '有问题先问它。岗位方向、技能学习顺序、简历与项目包装、面试准备，本机模型逐字作答，只聊天、不动你的任何数据。',
    to: '/assistant',
    cta: '去提问',
    icon: 'M4 5h16v10H9l-5 4z M8 9h8 M8 12h5',
  },
  {
    key: 'plan',
    title: '求职规划（岗位分析）',
    desc: '填一份画像，再把招聘页的「任职要求」整段粘进来 —— 任何专业、任何岗位都能分析。七个专职 Agent 顺序跑完，给出岗位要求、能力差距、学习路线与项目建议。',
    to: '/analyze',
    cta: '发起规划',
    icon: 'M12 3v4 M12 17v4 M5 12h4 M15 12h4 M8 8l8 8 M16 8l-8 8',
  },
  {
    key: 'tasks',
    title: '学习与项目任务',
    desc: '把规划落成可执行清单：逐条学习阶段与实战项目，做完提交证据，让系统知道你已经推进到哪。',
    to: '/tasks',
    cta: '去执行',
    icon: 'M9 6h11 M9 12h11 M9 18h11 M4 6l1.4 1.4L8 4.8 M4 12l1.4 1.4L8 10.8 M4 18l1.4 1.4L8 16.8',
  },
  {
    key: 'growth',
    title: '成长记录',
    desc: '记下你完成的事，据此升级技能等级、生成下一轮计划，看见自己一点点靠近目标岗位。',
    to: '/growth',
    cta: '看成长',
    icon: 'M3 17l6-6 4 4 8-9 M21 6h-5 M21 6v5',
  },
  {
    key: 'status',
    title: '系统状态',
    desc: '想知道本机模型是否就绪、或后端连不上时，来这里排查 —— 运维读数都在这一页。',
    to: '/status',
    cta: '查状态',
    icon: 'M12 3a9 9 0 100 18 9 9 0 000-18z M8 12h2l1.5 3.5L14 8.5 15.5 12H17',
  },
]

// ── 怎么用：一条真实的上手顺序（编号即顺序，不是装饰）──────────────────
const startSteps = [
  { step: 1, title: '先问 AI 助手', desc: '方向不明时先聊两句', to: '/assistant' },
  { step: 2, title: '发起一次求职规划', desc: '填画像、粘招聘要求原文', to: '/analyze' },
  { step: 3, title: '认领学习与项目任务', desc: '照着清单一条条推进', to: '/tasks' },
  { step: 4, title: '提交完成、推进下一轮', desc: '在成长记录里看等级变化', to: '/growth' },
]

// ── 上手须知：真实约束与演示入口，纯说明、可点的地方给去处 ──────────────
const notes = [
  { text: '全程离线：所有推理都在这台电脑上完成，不连云端、不用任何密钥。', link: { to: '/status', label: '查看本机状态' } },
  { text: '一次求职规划要依次跑七个步骤，通常几十秒到几分钟；期间可以切走，跑完再回来看结果。' },
  { text: '个人画像只存在这台浏览器里，随每次分析临时提交，服务器不做留存 —— 换浏览器需要重填。', link: { to: '/analyze', label: '去填画像' } },
  { text: '分析结果只在当前浏览器会话里保留，刷新即清空；真正长期保存的是「成长记录」里的历史。', link: { to: '/growth', label: '去成长记录' } },
  { text: '想先零成本体验：用演示账号 demo / demo1234 登录即可（只读浏览这些页面够用）。' },
]

/**
 * 一条工作流的产出落点。岗位要求 / 差距 / 学习路线 / 项目推荐不是独立页面，
 * 而是同一条七节点工作流里的节点，所以写成结果页内的区块锚点，不伪装成入口。
 */
const outputs = [
  { key: 'req', label: '岗位要求与依据原文', to: '/analyze', hash: '#card-requirements', where: '分析结果页' },
  { key: 'gap', label: '能力差距', to: '/analyze', hash: '#card-gaps', where: '分析结果页' },
  { key: 'learning', label: '学习路线', to: '/analyze', hash: '#card-learning', where: '分析结果页' },
  { key: 'project', label: '项目推荐', to: '/analyze', hash: '#card-projects', where: '分析结果页' },
]

// ── 七节点脊柱：节点名与顺序与 graph/workflow.py 的 ORDER 一致 ────────────
const flow = computed(() =>
  AGENTS.map((agent) => ({ ...agent, group: AGENT_GROUP[agent.group] })),
)

/** 色族 → 节点数，全部由 AGENTS 现算，不写死。 */
const legend = computed(() =>
  Object.entries(AGENT_GROUP).map(([key, group]) => ({
    key,
    label: group.label,
    color: group.color,
    count: AGENTS.filter((agent) => agent.group === key).length,
  })),
)
</script>

<template>
  <div class="ov-page">
    <!-- A. 欢迎 + 怎么用：左主张、右四步上手，不套框、不放读数 -->
    <section class="ov-hero">
      <div>
        <p class="ov-eyebrow">本地化 AI 求职规划 · 面向大学生与应届生</p>
        <h1>让 AI 帮你规划下一步职业成长</h1>
        <div class="ov-hero-actions">
          <router-link class="btn btn-primary" to="/assistant">开始 AI 咨询 →</router-link>
          <router-link class="ov-hero-alt" to="/analyze">或者发起一次求职规划</router-link>
        </div>
      </div>

      <!-- 签名件：一条四步上手序列（编号是真顺序），兼作最省事的跳转入口 -->
      <aside class="ov-rail ov-start" aria-label="四步上手">
        <p class="ov-rail-title">怎么用 · 四步上手</p>
        <div class="ov-start-list">
          <RouterLink
            v-for="item in startSteps"
            :key="item.step"
            class="ov-start-item"
            :to="item.to"
          >
            <span class="ov-start-num">{{ item.step }}</span>
            <span class="ov-start-text">
              <strong>{{ item.title }}</strong>
              <span>{{ item.desc }}</span>
            </span>
            <span class="ov-start-arrow" aria-hidden="true">→</span>
          </RouterLink>
        </div>
      </aside>
    </section>

    <!-- B. 有什么能用：五个真实页面，各说清用来干什么、去哪 -->
    <div class="page-head">
      <h2>有什么能用</h2>
      <p>五个入口对应五个真实页面，先看清楚各自用来干什么，再决定点哪个。</p>
    </div>

    <div class="ov-entries">
      <RouterLink v-for="item in features" :key="item.key" class="ov-entry" :to="item.to">
        <span class="ov-entry-icon" :aria-hidden="true">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.7"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path :d="item.icon" />
          </svg>
        </span>
        <div>
          <h3>{{ item.title }}</h3>
          <p>{{ item.desc }}</p>
        </div>
        <span class="ov-entry-go">
          {{ item.cta }}
          <span class="ov-entry-arrow" aria-hidden="true">→</span>
        </span>
      </RouterLink>
    </div>

    <!-- C. 怎么工作：一条七节点脊柱 + 色族图例 + 产出落点跳转 -->
    <section class="panel">
      <div class="panel-head">
        <h2>一条工作流，七个 Agent</h2>
        <span class="panel-src">七个步骤依次执行</span>
      </div>

      <p class="loose-note muted">
        「求职规划」背后是七个各司其职的 Agent 顺序跑一遍：先认识你、再查真实岗位要求、
        然后对齐差距、最后排出学习路线和项目。它们不是七个页面，是同一条链上的七步。
      </p>

      <div class="ov-spine">
        <article
          v-for="agent in flow"
          :key="agent.node"
          class="ov-station"
          :style="{ '--agent-color': agent.group.color }"
        >
          <div class="ov-station-no">
            <span>{{ agent.order }}</span>
            <span class="ov-station-group">{{ agent.group.label }}</span>
          </div>
          <h3>{{ agent.displayName }}</h3>
        </article>
      </div>

      <div class="ov-legend">
        <span v-for="item in legend" :key="item.key" class="ov-legend-item">
          <span class="ov-swatch" :style="{ background: item.color }" :aria-hidden="true" />
          {{ item.label }} · {{ item.count }} 个节点
        </span>
      </div>

      <div class="ov-outputs">
        <RouterLink
          v-for="item in outputs"
          :key="item.key"
          class="ov-output"
          :to="`${item.to}${item.hash}`"
        >
          {{ item.label }}
          <small>{{ item.where }}</small>
        </RouterLink>
      </div>

      <p class="faint block-note">
        跑完后这些产出会出现在岗位分析结果页的对应区块。整条链只有排队、进行中、完成、
        失败四种状态，所以过程中不给每个步骤编假进度。
      </p>
    </section>

    <!-- D. 上手须知：真实约束与演示入口，把该给去处都给了 -->
    <section class="panel">
      <div class="panel-head">
        <h2>上手须知</h2>
        <span class="panel-src">开始之前值得知道的事</span>
      </div>
      <ul class="plain-list muted">
        <li v-for="(item, i) in notes" :key="i">
          {{ item.text }}
          <RouterLink v-if="item.link" :to="item.link.to" class="ov-inline-link">
            {{ item.link.label }} →
          </RouterLink>
        </li>
      </ul>
    </section>
  </div>
</template>
