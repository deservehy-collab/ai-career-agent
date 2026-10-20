<script setup>
/**
 * 认证页骨架：左品牌区 + 右表单卡。
 *
 * 品牌区只回答使用者真正关心的两件事 —— 这是一个什么平台、登录后能干什么，
 * 用大白话说清楚，不摆工作流节点、源码路径、系统健康探测这类实现细节，
 * 也不放"示例数据"装成真实进度。
 * 整页纯静态、不发任何请求。
 */
defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
})

const intro =
  '面向大学生与应届生的 AI 求职规划平台：帮你想清楚方向、补齐能力差距，再把计划真正做完。'

// 登录后能干什么 —— 全部对应确实存在的功能页面，不夸大。
// 图形都按 22px 下还能认出来挑：不画整圈外框（会和图标底撞成双环），
// 不画 3px 以内的对勾（缩下去就是一粒噪点）。
const capabilities = [
  {
    key: 'ask',
    title: '随时问 AI 助手',
    desc: '岗位方向、学习顺序、简历面试，想到就问。',
    icon: 'M20 4H4v13h4v4l5-4h7z',
  },
  {
    key: 'plan',
    title: '一键生成求职规划',
    desc: '岗位要求、能力差距、学习路线与项目建议，一次给全。',
    icon: 'M6 3h8l4 4v14H6z M14 3v4h4 M9 12h6 M9 16h4',
  },
  {
    key: 'execute',
    title: '照着清单去执行',
    desc: '把规划拆成可完成的学习与项目任务，边做边打卡。',
    icon: 'M4 5h4v4H4z M4 15h4v4H4z M11 7h9 M11 17h9',
  },
  {
    key: 'grow',
    title: '看见自己的成长',
    desc: '记录每一次完成，等级与下一轮计划随进度更新。',
    icon: 'M3 17l6-6 4 4 8-8 M15 7h6v6',
  },
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
