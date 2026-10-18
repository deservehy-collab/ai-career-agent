<script setup>
/**
 * 认证页骨架：左品牌区 + 右表单卡。
 *
 * 品牌区只回答使用者真正关心的两件事 —— 这是一个什么平台、登录后能干什么，
 * 用大白话说清楚，不摆工作流节点、源码路径、系统健康探测这类实现细节。
 * 整页纯静态、不发任何请求；成长轨迹卡是示意图，数字不是真实读数。
 */
defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
})

const intro =
  '面向大学生与应届生的 AI 求职规划平台：帮你想清楚方向、补齐能力差距，再把计划真正做完。'

// 登录后能干什么 —— 全部对应确实存在的功能页面，不夸大。
const capabilities = [
  {
    key: 'ask',
    title: '随时问 AI 助手',
    desc: '岗位方向、学习顺序、简历面试，想到就问。',
    icon: 'M4 5h16v10H9l-5 4z M8 9h8 M8 12h5',
  },
  {
    key: 'plan',
    title: '一键生成求职规划',
    desc: '岗位要求、能力差距、学习路线与项目建议，一次给全。',
    icon: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z M16 8l-2 6-6 2 2-6z',
  },
  {
    key: 'execute',
    title: '照着清单去执行',
    desc: '把规划拆成可完成的学习与项目任务，边做边打卡。',
    icon: 'M9 6h11 M9 12h11 M9 18h11 M4 6l1.4 1.4L8 4.8 M4 12l1.4 1.4L8 10.8 M4 18l1.4 1.4L8 16.8',
  },
  {
    key: 'grow',
    title: '看见自己的成长',
    desc: '记录每一次完成，等级与下一轮计划随进度更新。',
    icon: 'M3 17l6-6 4 4 8-9 M21 6h-5 M21 6v5',
  },
]

// 四段等级条 = 未掌握 / 初级 / 中级 / 高级。示例里最高只到「中级」，
// 因为规则上学习类封顶初级、项目类封顶中级，「高级」不由任务授予。
const MAX_LEVEL = 4
const ladder = [
  { key: 'rag', skill: '向量检索 RAG', level: 3, change: '初级 → 中级', up: true },
  { key: 'graph', skill: 'LangGraph 编排', level: 2, change: '初级', up: false },
  { key: 'deliver', skill: '项目交付', level: 3, change: '中级', up: false },
]
</script>

<template>
  <div class="auth-shell">
    <section class="auth-brand">
      <div class="auth-brand-inner">
        <div class="auth-mark">
          <span class="auth-logo">CA</span>
          <span class="auth-mark-name">AI Career Agent</span>
        </div>

        <h1 class="auth-headline">让 AI 帮你规划<br /><em>下一步</em>职业成长</h1>
        <p class="auth-intro">{{ intro }}</p>

        <ul class="auth-pillars">
          <li v-for="item in capabilities" :key="item.key">
            <span class="auth-pillar-icon" aria-hidden="true">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path :d="item.icon" />
              </svg>
            </span>
            <div>
              <strong>{{ item.title }}</strong>
              <span>{{ item.desc }}</span>
            </div>
          </li>
        </ul>

        <div class="auth-ladder">
          <div class="auth-ladder-head">
            <span class="auth-ladder-title">成长轨迹</span>
            <span class="auth-ladder-round mono">示例 · 第 3 轮</span>
          </div>
          <div class="auth-ladder-rows">
            <div v-for="row in ladder" :key="row.key" class="auth-ladder-row">
              <span class="auth-ladder-skill">{{ row.skill }}</span>
              <span
                class="auth-ladder-level"
                :class="{ 'is-up': row.up }"
              >{{ row.change }}</span>
              <span class="auth-ladder-bars" aria-hidden="true">
                <i
                  v-for="n in MAX_LEVEL"
                  :key="n"
                  class="auth-ladder-seg"
                  :class="{ 'is-on': n <= row.level }"
                ></i>
              </span>
            </div>
          </div>
          <p class="auth-ladder-note">每完成一项任务就记一次，等级每轮最多升一档、只升不降。</p>
        </div>
      </div>
    </section>

    <section class="auth-panel">
      <div class="auth-form">
        <header class="auth-form-head">
          <h2>{{ title }}</h2>
          <p v-if="subtitle">{{ subtitle }}</p>
        </header>

        <slot />

        <footer v-if="$slots.foot" class="auth-foot">
          <slot name="foot" />
        </footer>
      </div>

      <p class="auth-trust">
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <path d="M12 3l8 3v6c0 4.5-3.4 7.6-8 9-4.6-1.4-8-4.5-8-9V6z" />
        </svg>
        <span>画像与成长记录都保存在你自己的电脑上</span>
      </p>
    </section>
  </div>
</template>
