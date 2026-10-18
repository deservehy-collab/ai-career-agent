<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import AppBadge from './AppBadge.vue'
import { formatDuration } from '../utils/format'
import { runStatusText, runStatusTone } from '../utils/enums'

/**
 * 后台运行进度卡。
 *
 * ⚠️ 后端只提供四态（queued / running / succeeded / failed），**没有进度百分比**。
 * 因此这里只用「已耗时计时 + 不确定进度条」表达"正在跑"，
 * 绝不显示任何伪造的百分比数字。
 */
const props = defineProps({
  status: { type: String, default: 'idle' },
  runId: { type: String, default: null },
  startedAt: { type: String, default: null },
  finishedAt: { type: String, default: null },
  errorMessage: { type: String, default: '' },
  errorKind: { type: String, default: null },
  title: { type: String, default: '分析进度' },
})

const now = ref(Date.now())
let timer = null

function startTicking() {
  stopTicking()
  now.value = Date.now()
  timer = setInterval(() => {
    now.value = Date.now()
  }, 1000)
}

function stopTicking() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

const isRunning = computed(() => props.status === 'queued' || props.status === 'running')

watch(
  isRunning,
  (running) => {
    if (running) startTicking()
    else stopTicking()
  },
  { immediate: true },
)

onBeforeUnmount(stopTicking)

const elapsedSeconds = computed(() => {
  if (!props.startedAt) return 0
  const from = new Date(props.startedAt).getTime()
  const to = props.finishedAt ? new Date(props.finishedAt).getTime() : now.value
  if (Number.isNaN(from) || Number.isNaN(to)) return 0
  return Math.max(0, Math.round((to - from) / 1000))
})

const statusText = computed(() => {
  if (props.status === 'idle') return '尚未开始'
  return runStatusText(props.status)
})

const tone = computed(() => runStatusTone(props.status))
</script>

<template>
  <section v-if="status !== 'idle'" class="card">
    <div class="card-head">
      <h2>
        {{ title }}
        <span class="sub">本地模型推理，通常需要数十秒到数分钟</span>
      </h2>
      <AppBadge :text="statusText" :tone="tone" />
    </div>

    <div class="card-body">
      <div v-if="isRunning">
        <div class="progress-indeterminate" />
        <p class="muted run-line">
          {{
            status === 'queued'
              ? '任务已排队。后台按单线程串行执行，请稍候…'
              : '模型正在分析岗位、能力与学习路线…'
          }}
        </p>
        <p class="faint run-line run-line--tight">
          已等待 <strong>{{ formatDuration(elapsedSeconds) }}</strong>
          <span v-if="runId"> · run_id <code class="mono">{{ runId }}</code></span>
        </p>
      </div>

      <div v-else-if="status === 'succeeded'">
        <div class="notice notice-ok">分析完成，用时 {{ formatDuration(elapsedSeconds) }}。</div>
      </div>

      <div v-else-if="status === 'failed'">
        <div class="notice notice-danger">
          <strong>
            {{
              errorKind === 'network'
                ? '无法连接后端'
                : errorKind === 'notfound'
                  ? '运行记录已失效'
                  : errorKind === 'timeout'
                    ? '等待超时'
                    : '分析失败'
            }}
          </strong>
          <div class="run-line run-line--tight">{{ errorMessage }}</div>
          <div class="run-line run-line--loose faint">你的画像已保留，可以直接重新发起。</div>
        </div>
      </div>
    </div>
  </section>
</template>
