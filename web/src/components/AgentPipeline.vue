<script setup>
import { computed } from 'vue'

import AppBadge from './AppBadge.vue'
import { AGENTS, AGENT_GROUP } from '../utils/agents'

/**
 * Agent 工作流流程轨。
 *
 * 关于"执行状态"的硬约束（后端能力决定，不能凭想象画）
 * --------------------------------------------------
 * - 工作流是**纯顺序图、无条件边**（graph/workflow.py 全是 add_edge），7 个节点每次都会执行；
 * - 后端 run 记录只有四态，**没有任何节点级信息**（backend/jobs.py 的 TaskRecord）。
 *
 * 因此：
 *   · 运行中 → 只在**整条轨**上显示不确定态，**不给任何单个节点标"正在执行"**；
 *   · 成功后 → 用 summarizeWorkflow(result) 的**真实产出计数**回填到各节点；
 *   · 失败   → 只标"执行中断"，**不把错误归因到某个节点**（后端只回一个错误字符串）；
 *   · 字段缺失 → 中性说明，不推测该节点失败或降级。
 */
const props = defineProps({
  /** summarizeWorkflow(result) 的结果；null 表示还没有结果 */
  summary: { type: Object, default: null },
  /** 运行状态：idle / queued / running / succeeded / failed */
  status: { type: String, default: 'idle' },
})

const emit = defineEmits(['navigate'])

const isRunning = computed(() => props.status === 'queued' || props.status === 'running')
const isInterrupted = computed(() => props.status === 'failed')

/**
 * 单个节点的产出摘要；没有结果时返回 null（节点整体呈中性，不显示任何产出）。
 * present === false 表示"结果里根本没有该节点的产出字段"——一无所知，不能说它失败或降级。
 */
function outputOf(agent) {
  const item = props.summary?.[agent.node]
  if (!item) return null

  if (item.present === false) {
    return { text: '无该节点数据', tone: 'muted', note: item.note || '' }
  }

  return {
    text: `${item.count} ${agent.outputLabel}`,
    tone: item.degraded ? 'warn' : item.count > 0 ? 'ok' : 'muted',
    note: item.note || '',
  }
}

/** 预计算每个节点要渲染的全部内容，模板里不再重复计算。 */
const nodes = computed(() =>
  AGENTS.map((agent) => {
    const group = AGENT_GROUP[agent.group]
    return {
      ...agent,
      colorStyle: { '--agent-color': group.color, '--agent-soft': group.soft },
      output: outputOf(agent),
      tip: agent.duty,
    }
  }),
)

function goTo(agent) {
  if (!props.summary) return
  const target = document.getElementById(agent.anchor)
  if (!target) return
  target.scrollIntoView({ behavior: 'smooth', block: 'start' })
  emit('navigate', agent.node)
}
</script>

<template>
  <section class="rail" aria-label="Agent 工作流">
    <div class="rail-head">
      <h2>Agent 工作流</h2>
      <AppBadge v-if="isRunning" text="执行中" tone="primary" />
      <AppBadge v-else-if="isInterrupted" text="执行中断" tone="danger" />
      <AppBadge v-else-if="summary" text="已完成" tone="ok" />
      <AppBadge v-else text="待运行" tone="muted" />
    </div>

    <div class="agent-rail" :class="{ 'is-running': isRunning, 'is-interrupted': isInterrupted }">
      <button
        v-for="node in nodes"
        :key="node.node"
        type="button"
        class="agent-node"
        :class="{ 'is-idle': !summary, 'is-degraded': node.output?.tone === 'warn' }"
        :style="node.colorStyle"
        :disabled="!summary"
        :title="node.tip"
        @click="goTo(node)"
      >
        <span class="agent-node-top">
          <span class="agent-tag-num">{{ node.order }}</span>
          <span class="agent-node-name">{{ node.displayName }}</span>
        </span>

        <span class="agent-node-duty">{{ node.duty }}</span>

        <template v-if="node.output">
          <span class="agent-node-out">
            <AppBadge :text="node.output.text" :tone="node.output.tone" />
          </span>
          <span v-if="node.output.note" class="agent-node-note">{{ node.output.note }}</span>
        </template>
      </button>
    </div>

    <div v-if="isRunning" class="notice notice-info">
      七个步骤正在依次进行，跑完后一次给出全部结果。中间步骤不给单独进度，请等它跑完。
    </div>

    <div v-else-if="isInterrupted" class="notice notice-danger">
      执行中断。暂时定位不到是哪一步出的问题，所以这里不指向具体节点 ——
      错误原因见右侧进度卡。
    </div>

    <p v-else-if="summary" class="faint block-note">
      点击任一节点可跳转到它在结果区对应的卡片。
    </p>
  </section>
</template>
