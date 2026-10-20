<script setup>
import AppBadge from './AppBadge.vue'
import { taskKindText, taskKindTone, taskStatusText, taskStatusTone } from '../utils/enums'
import { formatDateTime } from '../utils/format'

/**
 * 单个任务卡（agents/loop_store.py 的 task 结构）。
 * 真实字段：{task_id, kind(learning|project), round, index, title, skills[],
 *   status(pending|completed), created_at, completed_at, evidence}
 *
 * 任务只是"可勾选的一行"：模型写的计划原文不在任务里，而在 round 的
 * learning_plan / project_plan 中（见 TasksView 的计划明细区）。
 */
defineProps({
  task: { type: Object, required: true },
  /** 正在提交中的任务 ID（用于禁用按钮） */
  pendingId: { type: String, default: '' },
  /** 是否禁用提交（如存储不可写） */
  disabled: { type: Boolean, default: false },
})

defineEmits(['complete'])

const KIND_LETTER = { learning: '学习', project: '项目' }
</script>

<template>
  <article class="task-card" :class="{ 'is-done': task.status === 'completed' }">
    <header class="task-head">
      <AppBadge :text="taskKindText(task.kind)" :tone="taskKindTone(task.kind)" />
      <AppBadge :text="taskStatusText(task.status)" :tone="taskStatusTone(task.status)" />
      <span class="faint">第 {{ task.round }} 轮 · {{ KIND_LETTER[task.kind] || task.kind }}类</span>
    </header>

    <h3 class="task-title">{{ task.title || '（无标题）' }}</h3>

    <div class="tags tags--tight">
      <span v-for="skill in task.skills || []" :key="skill" class="badge">{{ skill }}</span>
      <span v-if="!(task.skills || []).length" class="faint">未关联技能</span>
    </div>

    <div v-if="task.status === 'completed'" class="task-done">
      <div class="faint">完成时间：{{ formatDateTime(task.completed_at) }}</div>
      <div class="muted">
        提交证据：{{ task.evidence || '（未填写证据 —— 该任务不会产生成长成果）' }}
      </div>
    </div>

    <div v-else class="btn-row task-actions">
      <button
        class="btn btn-primary"
        :disabled="disabled || pendingId === task.task_id"
        @click="$emit('complete', task)"
      >
        <span v-if="pendingId === task.task_id" class="spinner" />
        {{ pendingId === task.task_id ? '提交中…' : '提交完成证据' }}
      </button>
    </div>
  </article>
</template>
