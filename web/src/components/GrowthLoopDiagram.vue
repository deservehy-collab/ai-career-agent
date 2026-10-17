<script setup>
import { computed } from 'vue'

/**
 * 成长闭环示意图。
 *
 * ⚠️ status 必须**如实反映实现状态**：已实现的环节标 ready，尚未开放的标 pending（虚线灰底）。
 * 不允许为了图好看把未实现的环节画成可用 —— 那会让演示时点进去发现是空的。
 *
 * 维护约定：**每完成一个阶段（F2 / F3），回来把对应环节的 status 改成 'ready'，
 * 并把 note 换成真实文案**。默认值写在下面 DEFAULT_STAGES，集中一处好改。
 */
const DEFAULT_STAGES = [
  {
    key: 'profile',
    title: '① 填写画像',
    note: '专业 / 年级 / 技能 / 项目，保存在本机浏览器',
    status: 'ready',
  },
  {
    key: 'analyze',
    title: '② 岗位分析',
    note: '7 个专职 Agent 顺序协作，全程只读',
    status: 'ready',
  },
  {
    key: 'gaps',
    title: '③ 能力差距',
    note: '逐项对照岗位要求与当前能力，由代码判定等级与优先级',
    status: 'ready',
  },
  {
    key: 'plan',
    title: '④ 学习与项目计划',
    note: '按缺口排出学习阶段与实战项目',
    status: 'ready',
  },
  {
    key: 'practice',
    title: '⑤ 实践反馈',
    note: '在「学习与项目」页提交完成证据，成果进入待处理列表',
    status: 'ready',
  },
  {
    key: 'next-round',
    title: '⑥ 下一轮成长规划',
    note: '在成长记录页生成下一轮计划，成果这时才写入成长历史',
    status: 'ready',
  },
]

const props = defineProps({
  /** 不传则用内置的 DEFAULT_STAGES */
  stages: { type: Array, default: null },
})

const stages = computed(() => props.stages ?? DEFAULT_STAGES)

const readyCount = computed(() => stages.value.filter((s) => s.status === 'ready').length)
const hasPending = computed(() => stages.value.some((s) => s.status !== 'ready'))

function stepClass(stage) {
  return ['loop-step', stage.status === 'ready' ? 'is-ready' : 'is-pending']
}
</script>

<template>
  <section class="card">
    <div class="card-head">
      <h2>
        成长闭环
        <span class="sub">从画像到能力提升的完整链路</span>
      </h2>
      <span class="badge">
        {{ readyCount }} / {{ stages.length }} 环节已开放
      </span>
    </div>

    <div class="card-body">
      <div class="loop-row">
        <template v-for="(stage, index) in stages" :key="stage.key">
          <div :class="stepClass(stage)">
            <div class="loop-step-title">{{ stage.title }}</div>
            <div class="loop-step-note">{{ stage.note }}</div>
          </div>
          <span v-if="index < stages.length - 1" class="loop-arrow">→</span>
        </template>
      </div>

      <p v-if="hasPending" class="faint" style="margin: 12px 0 0">
        <span class="dot dot-warn" />
        虚线灰底的环节尚未开放，界面上不会展示这些环节的数据。
      </p>
    </div>
  </section>
</template>
