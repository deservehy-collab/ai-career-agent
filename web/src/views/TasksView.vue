<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'

import AgentTag from '../components/AgentTag.vue'
import AppBadge from '../components/AppBadge.vue'
import CompletionResult from '../components/CompletionResult.vue'
import LearningPlanList from '../components/LearningPlanList.vue'
import ProjectPlanList from '../components/ProjectPlanList.vue'
import TaskCard from '../components/TaskCard.vue'

import { completeTask, listTasks } from '../api/endpoints'
import { useProfileStore } from '../stores/profile'
import { storeStatusTone, storeStatusText } from '../utils/enums'

/**
 * 学习与项目页。
 *
 * 数据来自 `GET /api/tasks`：
 *   rounds[]        —— 全部轮次的摘要（只有计数）
 *   latest_round    —— **最新一轮的完整对象**，含 learning_plan / project_plan 明细
 *   tasks[]         —— 按 round_no 过滤后的任务清单
 *
 * ⚠️ 计划明细（阶段目标 / 完成标准 / 交付物）**只有 latest_round 里才有**；
 *    旧轮次在 rounds[] 中只有计数，后端也没有按轮次取计划的接口。
 *    所以旧轮次如实标注"计划明细仅最新一轮可查"，不做任何补全或猜测。
 */
const profile = useProfileStore()

// 与 backend/config.py 的 EVIDENCE_MAX_LENGTH 一致（前端无法读取后端配置，此处同步维护）
const EVIDENCE_MAX_LENGTH = 5000

const loading = ref(false)
const loadError = ref('')
const data = ref(null)

const selectedRound = ref(null)

const completingTask = ref(null)
const evidenceText = ref('')
const evidenceError = ref('')
const submitting = ref(false)
const submitError = ref('')
const submitResult = ref(null)

const rounds = computed(() => data.value?.rounds || [])
const latestRound = computed(() => data.value?.latest_round || null)
const latestRoundNo = computed(() => latestRound.value?.round ?? null)
const tasks = computed(() => data.value?.tasks || [])
const summary = computed(() => data.value?.summary || { total: 0, completed: 0, pending: 0 })

/** 存储不可写时禁止提交 —— 否则会做出"看起来提交成功、其实没落盘"的假象。 */
const readOnly = computed(() => data.value != null && data.value.writable === false)

const visibleTasks = computed(() =>
  selectedRound.value == null ? tasks.value : tasks.value.filter((t) => t.round === selectedRound.value),
)

/** 只有选中最新一轮（或未筛选）时才有计划明细可展示。 */
const planDetailRound = computed(() => {
  if (selectedRound.value == null) return latestRound.value
  return selectedRound.value === latestRoundNo.value ? latestRound.value : null
})

const showPlanLimitNote = computed(
  () => selectedRound.value != null && selectedRound.value !== latestRoundNo.value,
)

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    data.value = await listTasks()
  } catch (error) {
    data.value = null
    loadError.value = error?.message || '加载任务失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)

/** 弹层打开前所在的元素：关闭后把焦点还回去，键盘用户不会掉回页首。 */
let lastFocused = null

function openComplete(task) {
  lastFocused = document.activeElement
  completingTask.value = task
  evidenceText.value = ''
  evidenceError.value = ''
  submitError.value = ''
  submitResult.value = null
  nextTick(() => document.getElementById('tv-evidence')?.focus())
}

function restoreFocus() {
  nextTick(() => lastFocused?.focus?.())
  lastFocused = null
}

function closeComplete() {
  completingTask.value = null
  evidenceText.value = ''
  evidenceError.value = ''
  submitError.value = ''
  restoreFocus()
}

/** 与后端 StringConstraints(strip_whitespace, min_length=1, max_length=5000) 对齐。 */
function validateEvidence(text) {
  const trimmed = String(text ?? '').trim()
  if (!trimmed) return '证据不能为空 —— 只有标题不会带来任何升级。'
  if (trimmed.length > EVIDENCE_MAX_LENGTH) {
    return `证据过长（${trimmed.length} 字），最多 ${EVIDENCE_MAX_LENGTH} 字。`
  }
  return ''
}

async function submit() {
  if (!completingTask.value || submitting.value) return

  const problem = validateEvidence(evidenceText.value)
  evidenceError.value = problem
  if (problem) return

  submitting.value = true
  submitError.value = ''

  const body = { evidence: evidenceText.value.trim() }
  // 传了它，本次预览才与 growth_node 用同一基线（历史 ∪ 画像）；
  // 没做过分析时没有这张表，此时后端会退回 history_only 基线并如实提示。
  if (profile.hasLastSkills) body.profile_skills = profile.lastSkills

  try {
    submitResult.value = await completeTask(completingTask.value.task_id, body)
    completingTask.value = null
    evidenceText.value = ''
    restoreFocus()
    await load()
  } catch (error) {
    submitError.value = error?.message || '提交失败'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div>
    <div class="page-head">
      <h1>学习与项目</h1>
      <p>
        按轮次查看学习阶段与实战项目任务，提交完成证据后由成长节点评估技能升级。
        任务通过「成长记录」页的「生成下一轮」创建（岗位分析本身只出报告、不建任务）；
        首次运行请先到「成长记录」页提交一条已完成的学习/项目成果，再点击「生成下一轮」。
      </p>
    </div>

    <!-- 加载 / 失败 -->
    <div v-if="loading && !data" class="card">
      <div class="card-body"><div class="empty">正在加载任务…</div></div>
    </div>

    <div v-else-if="loadError" class="notice notice-danger">
      <strong>加载任务失败</strong>
      <div style="margin-top: 4px">{{ loadError }}</div>
      <div style="margin-top: 8px"><button class="btn" @click="load">重试</button></div>
    </div>

    <template v-else-if="data">
      <!-- 存储只读 / 异常 -->
      <div v-if="!data.writable" class="notice notice-warn">
        <strong>任务记录当前不可安全写入</strong>
        <div style="margin-top: 4px">
          {{ data.warning || 'runs/loop.json 处于不可写状态（损坏 / 版本不符 / 权限问题），为避免覆盖现有数据，提交功能已禁用。' }}
        </div>
      </div>

      <div v-else-if="data.store_status !== 'ok' && data.store_status !== 'empty'" class="notice notice-warn">
        任务记录状态：{{ storeStatusText(data.store_status) }}
      </div>

      <!-- 提交结果（三件事分开呈现） -->
      <CompletionResult v-if="submitResult" :result="submitResult" />
      <div v-if="submitResult" class="btn-row" style="margin-bottom: 16px">
        <button class="btn" @click="submitResult = null">收起提交结果</button>
      </div>

      <!-- 提交弹层 -->
      <div v-if="completingTask" class="modal-backdrop" @click.self="closeComplete">
        <div
          class="modal"
          role="dialog"
          aria-modal="true"
          aria-labelledby="tv-modal-title"
          @keydown.esc="closeComplete"
        >
          <div class="modal-head">
            <h2 id="tv-modal-title">
              提交完成证据
              <span class="sub mono">{{ completingTask.task_id }}</span>
            </h2>
          </div>
          <div class="modal-body">
            <p class="muted" style="margin-top: 0">
              {{ completingTask.title }}
              <span class="faint">（关联技能：{{ (completingTask.skills || []).join('、') || '无' }}）</span>
            </p>

            <div class="field">
              <label for="tv-evidence">
                实践证据
                <span class="hint">具体做了什么、有什么产出；空白或超过 {{ EVIDENCE_MAX_LENGTH }} 字会被拒绝</span>
              </label>
              <textarea
                id="tv-evidence"
                v-model="evidenceText"
                rows="5"
                placeholder="例：实现了文档切分与向量检索，用 20 条问题做了召回测试，命中率 85%"
              />
              <div class="faint" style="margin-top: 4px">
                {{ evidenceText.trim().length }} / {{ EVIDENCE_MAX_LENGTH }}
              </div>
            </div>

            <div v-if="evidenceError" class="notice notice-warn">{{ evidenceError }}</div>
            <div v-if="submitError" class="notice notice-danger">{{ submitError }}</div>

            <div class="notice notice-info" style="margin-bottom: 0">
              提交后会同时得到三样东西：<strong>任务完成记录</strong>（真正落盘）、
              <strong>成长成果</strong>（可能构不成）、<strong>技能升级预览</strong>（不会立刻写入成长历史）。
            </div>
          </div>
          <div class="modal-foot">
            <button class="btn" :disabled="submitting" @click="closeComplete">取消</button>
            <button class="btn btn-primary" :disabled="submitting" @click="submit">
              <span v-if="submitting" class="spinner" />
              {{ submitting ? '提交中…' : '确认提交' }}
            </button>
          </div>
        </div>
      </div>

      <!-- 空态 -->
      <div v-if="!rounds.length" class="card">
        <div class="card-head"><h2>还没有任何轮次</h2></div>
        <div class="card-body">
          <div class="empty">
            还没有任务。任务要在「成长记录」页提交一条已完成的学习/项目成果后，
            点击<router-link to="/growth">「生成下一轮」</router-link>才会创建。
            岗位分析（<router-link to="/analyze">去分析</router-link>）只输出诊断报告，不会自动建任务。
          </div>
        </div>
      </div>

      <template v-else>
        <!-- 轮次与进度 -->
        <section class="card">
          <div class="card-head">
            <h2>
              任务进度
              <span class="sub">共 {{ rounds.length }} 轮，{{ summary.completed }} / {{ summary.total }} 项完成</span>
            </h2>
            <div class="btn-row">
              <AppBadge
                :text="`待完成 ${summary.pending}`"
                :tone="summary.pending ? 'warn' : 'ok'"
              />
              <AppBadge :text="storeStatusText(data.store_status)" :tone="storeStatusTone(data.store_status)" />
              <button class="btn" :disabled="loading" @click="load">
                {{ loading ? '刷新中…' : '刷新' }}
              </button>
            </div>
          </div>
          <div class="card-body">
            <div class="round-tabs" role="group" aria-label="按轮次筛选任务">
              <button
                class="btn"
                :class="{ 'btn-primary': selectedRound === null }"
                @click="selectedRound = null"
              >
                全部轮次
              </button>
              <button
                v-for="round in rounds"
                :key="round.round"
                class="btn"
                :class="{ 'btn-primary': selectedRound === round.round }"
                @click="selectedRound = round.round"
              >
                第 {{ round.round }} 轮（{{ round.completed_count }}/{{ round.task_count }}）
              </button>
            </div>
            <p class="faint round-tabs-hint">
              目标岗位：
              {{ (rounds.find((r) => r.round === (selectedRound ?? latestRoundNo)) || {}).target_job || '未记录' }}
            </p>
          </div>
        </section>

        <!-- 任务清单 -->
        <section class="card">
          <div class="card-head">
            <h2>
              任务清单
              <span class="sub">{{ visibleTasks.length }} 项</span>
            </h2>
          </div>
          <div class="card-body">
            <div v-if="!visibleTasks.length" class="empty">该轮次没有任务。</div>
            <div v-else class="task-grid">
              <TaskCard
                v-for="task in visibleTasks"
                :key="task.task_id"
                :task="task"
                :pending-id="submitting ? completingTask?.task_id ?? '' : ''"
                :disabled="readOnly"
                @complete="openComplete"
              />
            </div>
          </div>
        </section>

        <!-- 计划明细：只有最新一轮拿得到 -->
        <template v-if="planDetailRound">
          <div v-if="(planDetailRound.learning_plan || []).length">
            <LearningPlanList :stages="planDetailRound.learning_plan" agent-node="learning" />
          </div>
          <div v-if="(planDetailRound.project_plan || []).length">
            <ProjectPlanList :projects="planDetailRound.project_plan" agent-node="project" />
          </div>
        </template>

        <div v-else-if="showPlanLimitNote" class="notice notice-info">
          计划明细（阶段目标 / 完成标准 / 项目交付物）<strong>仅最新一轮可查</strong> ——
          接口只在 <span class="mono">latest_round</span> 里返回
          <span class="mono">learning_plan</span> 与 <span class="mono">project_plan</span> 全文。
          历史轮次在 <span class="mono">rounds[]</span> 中只有计数，这里不做补全。
        </div>
      </template>
    </template>
  </div>
</template>