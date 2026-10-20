<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'

import AgentTag from '../components/AgentTag.vue'
import AppBadge from '../components/AppBadge.vue'
import CompletionResult from '../components/CompletionResult.vue'
import LearningPlanList from '../components/LearningPlanList.vue'
import ProjectPlanList from '../components/ProjectPlanList.vue'
import TaskCard from '../components/TaskCard.vue'

import { clearTasks, completeTask, getPending, listTasks } from '../api/endpoints'
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
 *
 * 「清空任务清单」走 `POST /api/tasks/clear`：**先备份再重置**，只动任务清单，
 * 成长历史一行不碰。但打卡攒下、还没进成长历史的成果是挂在清单里的，
 * 会跟着一起消失 —— 所以弹层先查一次未记账条数摆给用户看，勾一下才放行。
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

// ── 清空任务清单 ───────────────────────────────────────────────────────
const clearing = ref(false)
const clearBusy = ref(false)
const clearError = ref('')
const clearResult = ref(null)
const dropPending = ref(false)
/** `null` = 还没查到；数字 = 打卡攒下、还没进成长历史的成果条数。 */
const pendingCount = ref(null)

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

/**
 * 「做到什么程度算完成」不在任务记录里 —— 任务只是可勾选的一行，
 * 文字原样躺在轮次的计划明细中，这里按 轮次 + 类型 + 序号 回填给用户照着写。
 * 旧轮次只有计数、没有明细，取不到就不显示这一行，绝不拿标题凑一句标准出来。
 */
const completingCriteria = computed(() => {
  const task = completingTask.value
  const round = latestRound.value
  if (!task || !round || round.round !== task.round) return null
  const isProject = task.kind === 'project'
  const plan = (isProject ? round.project_plan : round.learning_plan) || []
  const text = String((isProject ? plan[task.index - 1]?.deliverable
    : plan[task.index - 1]?.completion_criteria) || '').trim()
  return text ? { label: isProject ? '最终成果' : '完成标准', text } : null
})

/**
 * 清空要不要先勾一下：
 * 打卡攒下的成果还挂在任务清单里，要等「生成下一轮」才正式进成长历史 ——
 * 清空会把这批**还没记账**的进度一起带走，所以必须显式确认。
 * 条数查不到时按"不用勾"处理：后端还会再拦一次，不会偷偷丢。
 */
const clearNeedsAck = computed(() => (pendingCount.value ?? 0) > 0)
const clearBlocked = computed(() => clearNeedsAck.value && !dropPending.value)

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

/** 后端备份给的是完整路径，界面只显示文件名。 */
function backupName(path) {
  const parts = String(path ?? '').split(/[\\/]/)
  return parts[parts.length - 1] || ''
}

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

// ── 清空任务清单 ───────────────────────────────────────────────────────

/** 打开弹层时先查一次未记账成果，让用户在点下去之前就看到会带走几条真实进度。 */
async function openClear() {
  lastFocused = document.activeElement
  clearing.value = true
  clearError.value = ''
  dropPending.value = false
  pendingCount.value = null
  try {
    const pending = await getPending()
    pendingCount.value = (pending.events || []).length
  } catch {
    pendingCount.value = null
  }
}

function closeClear() {
  clearing.value = false
  clearError.value = ''
  dropPending.value = false
  restoreFocus()
}

async function confirmClear() {
  if (clearBusy.value || clearBlocked.value) return

  clearBusy.value = true
  clearError.value = ''
  try {
    const result = await clearTasks(dropPending.value)
    if (result.status === 'cleared') {
      clearing.value = false
      clearResult.value = result
      dropPending.value = false
      pendingCount.value = 0
      selectedRound.value = null
      restoreFocus()
      await load()
      return
    }
    if (result.status === 'needs_confirmation') {
      // 后端比前端更清楚有哪些成果没记账，以它的条数为准，勾上再重来一次。
      pendingCount.value = result.pending_events ?? 0
      clearError.value = `有 ${result.pending_events} 条成果还没正式记进成长历史，清空会把它们一起丢掉。`
      return
    }
    clearError.value = result.warning || '任务清单没能清空，已有记录一个字节都没动。'
  } catch (error) {
    clearError.value = error?.message || '清空失败'
  } finally {
    clearBusy.value = false
  }
}
</script>

<template>
  <div>
    <div class="page-head">
      <h1>学习与项目</h1>
      <p>
        任务有两个来源：第一次「岗位分析」会把当时给出的学习/项目计划存成第 1 轮，
        之后每一轮由「成长记录」页的「生成下一轮」创建。
        勾完任务写上证据，由成长节点评估技能升级。
        不想再看到这批任务，用「任务进度」卡片右侧的「清空任务清单」—— 它只清清单，不动成长历史。
      </p>
    </div>

    <!-- 加载 / 失败 -->
    <div v-if="loading && !data" class="card">
      <div class="card-body"><div class="empty">正在加载任务…</div></div>
    </div>

    <div v-else-if="loadError" class="notice notice-danger">
      <strong>加载任务失败</strong>
      <div class="notice-body">{{ loadError }}</div>
      <div class="btn-row"><button class="btn" @click="load">重试</button></div>
    </div>

    <template v-else-if="data">
      <!-- 存储只读 / 异常 -->
      <div v-if="!data.writable" class="notice notice-warn">
        <strong>任务清单现在不能安全保存</strong>
        <div class="notice-body">
          {{ data.warning || '清单文件读不出可用内容（损坏、版本不符或没有写权限）。为避免弄丢已有记录，提交功能先停用；具体原因见「系统状态」页。' }}
        </div>
      </div>

      <div v-else-if="data.store_status !== 'ok' && data.store_status !== 'empty'" class="notice notice-warn">
        任务记录状态：{{ storeStatusText(data.store_status) }}
      </div>

      <!-- 清空结果 -->
      <div v-if="clearResult" class="notice notice-ok">
        <strong>任务清单已清空</strong>
        <div class="notice-body">
          删掉了 {{ clearResult.rounds_removed }} 轮、共 {{ clearResult.tasks_removed }} 项任务；
          <strong>成长历史没有改动</strong>，已经正式记下来的历史一条都不会少。
          <template v-if="clearResult.backup">
            清空前的原清单备份为 <code class="mono">{{ backupName(clearResult.backup) }}</code>，需要还原就照着这个名字找回。
          </template>
          <template v-if="clearResult.pending_events">
            另外，{{ clearResult.pending_events }} 条还没记账的成果按你的确认一起丢弃了。
          </template>
        </div>
        <div class="btn-row btn-row--block">
          <button class="btn" @click="clearResult = null">收起清空结果</button>
        </div>
      </div>

      <!-- 提交结果（三件事分开呈现） -->
      <CompletionResult v-if="submitResult" :result="submitResult" />
      <div v-if="submitResult" class="btn-row btn-row--block">
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
            <h2 id="tv-modal-title">提交完成证据</h2>
          </div>
          <div class="modal-body">
            <p class="muted flush-first">{{ completingTask.title }}</p>
            <p class="faint modal-task-skills">
              <template v-if="(completingTask.skills || []).length">
                关联技能：{{ (completingTask.skills || []).join('、') }}
              </template>
              <template v-else>
                这条任务没有关联技能 —— 提交只会留下一条完成记录，不会带来技能升级。
              </template>
            </p>

            <div v-if="completingCriteria" class="modal-criteria">
              <span class="modal-criteria__label">{{ completingCriteria.label }}</span>
              <p class="modal-criteria__text">{{ completingCriteria.text }}</p>
            </div>

            <div class="field">
              <label for="tv-evidence">
                实践证据
                <span class="hint">
                  <template v-if="completingCriteria">
                    照上面的{{ completingCriteria.label }}，写你实际做了什么、留下了什么
                  </template>
                  <template v-else>具体做了什么、有什么产出</template>
                </span>
              </label>
              <textarea
                id="tv-evidence"
                v-model="evidenceText"
                rows="5"
                placeholder="例：把登录和打卡两个页面搭完了，用 10 条真实数据自测通过，没有报错"
              />
              <div class="faint field-count">
                {{ evidenceText.trim().length }} / {{ EVIDENCE_MAX_LENGTH }}
              </div>
            </div>

            <div v-if="evidenceError" class="notice notice-warn">{{ evidenceError }}</div>
            <div v-if="submitError" class="notice notice-danger">{{ submitError }}</div>

            <div class="notice notice-info flush-last">
              <template v-if="(completingTask.skills || []).length">
                提交后会同时得到三样东西：<strong>任务完成记录</strong>（真正落盘）、
                <strong>成长成果</strong>（可能构不成）、<strong>技能升级预览</strong>（不会立刻写入成长历史）。
              </template>
              <template v-else>
                这条提交只会留下一份<strong>任务完成记录</strong>（真正落盘），不会有成长成果，也不会有升级预览。
              </template>
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

      <!-- 清空弹层 -->
      <div v-if="clearing" class="modal-backdrop" @click.self="closeClear">
        <div
          class="modal"
          role="dialog"
          aria-modal="true"
          aria-labelledby="tv-clear-title"
          @keydown.esc="closeClear"
        >
          <div class="modal-head">
            <h2 id="tv-clear-title">清空任务清单</h2>
          </div>
          <div class="modal-body">
            <p class="muted flush-first">
              会删掉 <strong>{{ rounds.length }}</strong> 轮、共
              <strong>{{ summary.total }}</strong> 项任务（其中已完成
              {{ summary.completed }} 项），删完这一页回到「还没有任务」的状态。
            </p>

            <dl class="kv kv--mid">
              <dt>成长历史</dt>
              <dd>不受影响。已经正式记下来的升级与成果一条都不会少。</dd>
              <dt>原清单</dt>
              <dd>清空前自动备份一份，照着备份名可以还原。</dd>
              <dt>未记账成果</dt>
              <dd>
                <template v-if="pendingCount === null">
                  暂时查不到有没有。若真有，清空会先被拦住、一个字节都不删，回来告诉你条数。
                </template>
                <template v-else-if="pendingCount === 0">
                  没有。打卡攒下的成果都已经正式记账了。
                </template>
                <template v-else>
                  <strong class="is-warn">{{ pendingCount }} 条</strong>还没进成长历史，
                  清空会把这批真实进度一起带走。
                </template>
              </dd>
            </dl>

            <label v-if="clearNeedsAck" class="clear-ack">
              <input v-model="dropPending" type="checkbox" />
              <span>我确认连同这 {{ pendingCount }} 条未记账成果一起丢掉</span>
            </label>

            <div v-if="clearError" class="notice notice-danger">{{ clearError }}</div>

            <div class="notice notice-info flush-last">
              这里只清任务清单。想清空<b>画像与求职目标</b>，去「岗位分析」页用那边的清空按钮。
            </div>
          </div>
          <div class="modal-foot">
            <button class="btn" :disabled="clearBusy" @click="closeClear">取消</button>
            <button class="btn btn-danger" :disabled="clearBusy || clearBlocked" @click="confirmClear">
              <span v-if="clearBusy" class="spinner" />
              {{ clearBusy ? '清空中…' : '确认清空' }}
            </button>
          </div>
        </div>
      </div>

      <!-- 空态 -->
      <div v-if="!rounds.length" class="card">
        <div class="card-head"><h2>还没有任何轮次</h2></div>
        <div class="card-body">
          <div class="empty">
            还没有任务。做一次<router-link to="/analyze">岗位分析</router-link>，它给出的学习阶段与实战项目
            会自动存成第 1 轮；之后的每一轮，在<router-link to="/growth">成长记录</router-link>页点「生成下一轮」创建。
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
              <button class="btn btn-ghost" :disabled="readOnly || clearing" @click="openClear">
                清空任务清单
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
          这一轮只留下了任务计数，没有存阶段目标、完成标准和项目交付物的明细 ——
          <strong>明细只有最新一轮可查</strong>，更早的轮次不做补全。
        </div>
      </template>
    </template>
  </div>
</template>