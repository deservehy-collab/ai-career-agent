<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'

import CompletionResult from '../components/CompletionResult.vue'

import { clearTasks, completeTask, getPending, listTasks } from '../api/endpoints'
import { useProfileStore } from '../stores/profile'
import { storeStatusText, taskKindText, taskStatusText } from '../utils/enums'
import { joinList } from '../utils/format'

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
const visibleDone = computed(() => visibleTasks.value.filter((t) => t.status === 'completed').length)
const visiblePending = computed(() => visibleTasks.value.length - visibleDone.value)

/** 编号跟着整份清单走，筛到某一轮时也还是原来那个号，不对不上。 */
const taskNumbers = computed(() => {
  const map = new Map()
  tasks.value.forEach((task, index) => map.set(task.task_id, index + 1))
  return map
})

function taskNo(task) {
  return String(taskNumbers.value.get(task?.task_id) ?? '—').padStart(2, '0')
}

/** 按轮次分组：全部轮次视图里，组头负责交代每一段属于哪一轮。 */
const groupedTasks = computed(() => {
  const groups = []
  const seen = new Map()
  for (const task of visibleTasks.value) {
    let group = seen.get(task.round)
    if (!group) {
      group = { round: task.round, tasks: [], done: 0 }
      seen.set(task.round, group)
      groups.push(group)
    }
    group.tasks.push(task)
    if (task.status === 'completed') group.done += 1
  }
  return groups
})

const currentRound = computed(() => {
  const roundNo = selectedRound.value ?? latestRoundNo.value
  return rounds.value.find((round) => round.round === roundNo) || null
})
const targetJob = computed(() => currentRound.value?.target_job || '未记录')

const listStatusText = computed(() => {
  if (readOnly.value) return '只读 · 不能写入'
  if (data.value?.store_status === 'ok') return '已保存 · 可写入'
  return storeStatusText(data.value?.store_status)
})

const runningStatus = computed(() => {
  if (readOnly.value) return '只读'
  if (visiblePending.value) return '执行中'
  return visibleTasks.value.length ? '已完成' : '暂无任务'
})

/** 只有选中最新一轮（或未筛选）时才有计划明细可展示。 */
const planDetailRound = computed(() => {
  if (selectedRound.value == null) return latestRound.value
  return selectedRound.value === latestRoundNo.value ? latestRound.value : null
})

const learningPlan = computed(() => planDetailRound.value?.learning_plan || [])
const projectPlan = computed(() => planDetailRound.value?.project_plan || [])

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

function pad2(index) {
  return String(index + 1).padStart(2, '0')
}

/** 行内日期只到"几月几日"；解析失败就不显示，不假装成功。 */
function shortDate(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return `${date.getMonth() + 1} 月 ${date.getDate()} 日`
}

/** 弹层/抽屉打开前所在的元素：关闭后把焦点还回去，键盘用户不会掉回页首。 */
let lastFocused = null

function openComplete(task) {
  lastFocused = document.activeElement
  completingTask.value = task
  evidenceText.value = ''
  evidenceError.value = ''
  submitError.value = ''
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
    // 提交行的按钮会随任务变成"已完成"而消失，焦点不能再还给它；
    // 三段式结论是这次操作的新内容，直接把焦点送过去。
    lastFocused = null
    await load()
    nextTick(() => {
      const result = document.getElementById('tv-result')
      if (!result) return
      result.scrollIntoView({ block: 'start' })
      result.focus({ preventScroll: true })
    })
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
    <!-- 加载 / 失败 -->
    <div v-if="loading && !data" class="card">
      <div class="card-body"><div class="empty">正在加载任务…</div></div>
    </div>

    <div v-else-if="loadError" class="notice notice-danger">
      <strong>加载任务失败</strong>
      <div class="notice-body">{{ loadError }}</div>
      <div class="btn-row"><button class="btn" @click="load">重试</button></div>
    </div>

    <article v-else-if="data" class="reg">
      <header>
        <div class="reg-running">
          <span class="reg-brand">AI CAREER AGENT</span>
          <span>学习与项目</span>
          <span class="reg-running__right">
            当前 <b>{{ selectedRound == null ? '全部轮次' : `第 ${selectedRound} 轮` }}</b>
            · {{ runningStatus }}
          </span>
        </div>

        <div class="reg-mast">
          <div>
            <p class="reg-eyebrow">执行登记册 · 共 {{ rounds.length }} 轮</p>
            <h1 class="reg-title">学习与项目</h1>
          </div>
          <p class="reg-deck">
            把求职规划拆成今天就能动手的条目。做完一项，写下你实际做了什么 ——
            系统据此判断技能升级、安排下一轮。
          </p>
        </div>
      </header>

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
      <div
        v-if="submitResult"
        id="tv-result"
        class="reg-result-anchor"
        tabindex="-1"
        aria-live="polite"
      >
        <CompletionResult :result="submitResult" />
        <div class="btn-row btn-row--block reg-result-tools">
          <button class="btn" @click="submitResult = null">收起提交结果</button>
        </div>
      </div>

      <!-- 空态 -->
      <section v-if="!rounds.length" class="reg-empty">
        <h2 class="reg-empty-title">还没有任何轮次</h2>
        <p>
          还没有任务。做一次<router-link to="/analyze">岗位分析</router-link>，它给出的学习阶段与实战项目
          会自动存成第 1 轮；之后的每一轮，在<router-link to="/growth">成长记录</router-link>页点「生成下一轮」创建。
        </p>
      </section>

      <template v-else>
        <div class="reg-body">
          <aside class="reg-index" aria-label="进度与轮次">
            <div class="reg-figure-label">执行进度</div>
            <div class="reg-figure">
              <span>{{ visibleDone }}</span><i>/</i><span>{{ visibleTasks.length }}</span>
              <small>项已完成</small>
            </div>
            <div class="reg-ruler" aria-hidden="true">
              <span
                v-for="task in visibleTasks"
                :key="task.task_id"
                :class="{ 'is-done': task.status === 'completed' }"
              ></span>
            </div>

            <dl class="reg-facts">
              <div><dt>待完成</dt><dd>{{ visiblePending }} 项</dd></div>
              <div>
                <dt>轮次</dt>
                <dd>{{ selectedRound == null ? `${rounds.length} 轮` : `第 ${selectedRound} 轮` }}</dd>
              </div>
              <div><dt>目标岗位</dt><dd class="muted">{{ targetJob }}</dd></div>
              <div><dt>清单状态</dt><dd class="muted">{{ listStatusText }}</dd></div>
            </dl>

            <nav class="reg-rounds" aria-label="按轮次筛选任务">
              <p class="reg-rounds__label">按轮次查看</p>
              <button
                class="reg-round"
                :class="{ 'is-active': selectedRound === null }"
                :aria-pressed="selectedRound === null"
                type="button"
                @click="selectedRound = null"
              >
                全部轮次 <b>{{ summary.total }}</b>
              </button>
              <button
                v-for="round in rounds"
                :key="round.round"
                class="reg-round"
                :class="{ 'is-active': selectedRound === round.round }"
                :aria-pressed="selectedRound === round.round"
                type="button"
                @click="selectedRound = round.round"
              >
                第 {{ round.round }} 轮 <b>{{ round.completed_count }} / {{ round.task_count }}</b>
              </button>
            </nav>

            <div class="reg-actions">
              <button class="reg-quiet" type="button" :disabled="loading" @click="load">
                {{ loading ? '刷新中…' : '刷新' }}
              </button>
              <button
                class="reg-quiet reg-quiet--danger"
                type="button"
                :disabled="readOnly || clearing"
                @click="openClear"
              >
                清空任务清单
              </button>
            </div>
          </aside>

          <section class="reg-main" aria-labelledby="reg-list-title">
            <div class="reg-sec-head">
              <h2 id="reg-list-title">任务清单</h2>
              <span>{{ visibleTasks.length }} 项 · 按时间顺序</span>
            </div>

            <div class="reg-table-head" aria-hidden="true">
              <span>№</span><span>任务</span><span>技能</span><span>状态</span><span></span>
            </div>

            <div v-if="!visibleTasks.length" class="empty">该轮次没有任务。</div>

            <template v-else>
              <div v-for="group in groupedTasks" :key="group.round" class="reg-group">
                <div class="reg-group-head">
                  <span>第 {{ group.round }} 轮</span>
                  <span><b>{{ group.done }} / {{ group.tasks.length }}</b> 完成</span>
                </div>

                <article
                  v-for="task in group.tasks"
                  :key="task.task_id"
                  class="reg-row"
                  :class="{ 'is-done': task.status === 'completed' }"
                >
                  <span class="reg-no">{{ taskNo(task) }}</span>

                  <div>
                    <div class="reg-kicker">
                      <b>{{ taskKindText(task.kind) }}</b>
                      <span v-if="task.status === 'completed'" class="is-done">
                        {{ taskStatusText(task.status) }}
                        <template v-if="task.completed_at"> · {{ shortDate(task.completed_at) }}</template>
                      </span>
                      <span v-else>{{ taskStatusText(task.status) }}</span>
                    </div>

                    <h3 class="reg-task-title">{{ task.title || '（无标题）' }}</h3>

                    <p v-if="task.status === 'completed'" class="reg-sub">
                      <b>证据</b>{{ task.evidence || '（未填写证据 —— 该任务不会产生成长成果）' }}
                      <span v-if="task.completed_at" class="reg-sub-date">· {{ shortDate(task.completed_at) }} 完成</span>
                    </p>
                    <button
                      v-else
                      class="reg-submit reg-mobile-action"
                      type="button"
                      :disabled="readOnly"
                      @click="openComplete(task)"
                    >
                      提交证据 →
                    </button>
                  </div>

                  <div class="reg-skills">
                    <span v-for="skill in task.skills || []" :key="skill">{{ skill }}</span>
                    <span v-if="!(task.skills || []).length" class="is-none">未关联</span>
                  </div>

                  <span class="reg-status" :class="{ 'is-done': task.status === 'completed' }">
                    {{ taskStatusText(task.status) }}
                  </span>

                  <button
                    v-if="task.status !== 'completed'"
                    class="reg-submit"
                    type="button"
                    :disabled="readOnly || submitting"
                    @click="openComplete(task)"
                  >
                    提交 →
                  </button>
                  <span v-else></span>
                </article>
              </div>
            </template>
          </section>
        </div>

        <!-- 计划明细：只有最新一轮拿得到 -->
        <section
          v-if="planDetailRound && (learningPlan.length || projectPlan.length)"
          class="reg-app"
          id="reg-app"
        >
          <div class="reg-sec-head">
            <h2>附 · 第 {{ planDetailRound.round }} 轮计划原文</h2>
            <span>计划明细只有最新一轮可查</span>
          </div>
          <p class="reg-app-note">
            下面是这一轮任务的出处：每个阶段要练到什么程度、每个项目要交出什么。
            更早的轮次只留下任务计数，这里不做补全。
          </p>

          <div class="reg-app-grid">
            <div v-if="learningPlan.length">
              <h3>学习路线 <span>{{ learningPlan.length }} 个阶段</span></h3>
              <ol class="reg-app-list">
                <li v-for="(stage, i) in learningPlan" :key="i">
                  <span class="reg-app-no">{{ pad2(i) }}</span>
                  <div>
                    <h4>
                      {{ stage.topic || `阶段 ${stage.stage || i + 1}` }}
                      <em v-if="stage.estimated_weeks">约 {{ stage.estimated_weeks }} 周</em>
                    </h4>
                    <p class="reg-app-meta">
                      <span v-if="stage.goal">目标 {{ stage.goal }}</span>
                      <span v-if="(stage.covers || []).length">覆盖缺口 {{ joinList(stage.covers) }}</span>
                      <span>前置：{{ stage.prerequisite || '无特殊前置' }}</span>
                    </p>
                    <p v-if="stage.completion_criteria" class="reg-app-crit">
                      <b>完成标准</b>{{ stage.completion_criteria }}
                    </p>
                  </div>
                </li>
              </ol>
            </div>

            <div v-if="projectPlan.length">
              <h3>实战项目 <span>{{ projectPlan.length }} 个项目</span></h3>
              <ol class="reg-app-list">
                <li v-for="(project, i) in projectPlan" :key="i">
                  <span class="reg-app-no">{{ pad2(i) }}</span>
                  <div>
                    <h4>
                      {{ project.name || `项目 ${i + 1}` }}
                      <em v-if="project.difficulty || project.stage">
                        {{ project.difficulty }}<template v-if="project.difficulty && project.stage"> · </template>{{ project.stage }}
                      </em>
                    </h4>
                    <p class="reg-app-meta">
                      <span v-if="project.goal">目标 {{ project.goal }}</span>
                      <span>技术栈 {{ joinList(project.tech_stack) }}</span>
                      <span>缺口 {{ joinList(project.covers_gaps) }}</span>
                    </p>
                    <p v-if="project.deliverable" class="reg-app-crit">
                      <b>最终成果</b>{{ project.deliverable }}
                    </p>
                    <p v-if="project.blocked_reason" class="reg-app-meta is-warn">
                      {{ project.blocked_reason }}
                    </p>
                  </div>
                </li>
              </ol>
            </div>
          </div>
        </section>

        <div v-else-if="showPlanLimitNote" class="reg-app">
          <p class="reg-app-note">
            这一轮只留下了任务计数，没有存阶段目标、完成标准和项目交付物的明细 ——
            <strong>明细只有最新一轮可查</strong>，更早的轮次不做补全。
          </p>
        </div>

        <footer class="reg-foot">
          <span>清空任务清单只清这一页的任务；已经记进成长历史的升级一条都不会少。</span>
          <span>共 {{ rounds.length }} 轮 · {{ summary.total }} 项任务</span>
        </footer>
      </template>
    </article>

    <!-- 弹层挂到 body：留在视图根里会被切页的 opacity 动画困成新的层叠上下文，
         窄屏时固定抽屉会被顶部移动条盖住。 -->
    <Teleport to="body">
    <!-- 提交证据：右侧抽屉，写证据时清单还在视野里 -->
    <div v-if="completingTask" class="reg-sheet-backdrop" @click.self="closeComplete">
      <section
        class="reg-sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="tv-modal-title"
        @keydown.esc="closeComplete"
      >
        <div class="reg-sheet__head">
          <div>
            <div class="reg-sheet__eyebrow">
              任务 {{ taskNo(completingTask) }} · {{ taskKindText(completingTask.kind) }} ·
              第 {{ completingTask.round }} 轮
            </div>
            <h2 id="tv-modal-title">提交完成证据</h2>
          </div>
          <button class="reg-sheet__close" type="button" aria-label="关闭" @click="closeComplete">
            ×
          </button>
        </div>

        <p class="reg-sheet__task">{{ completingTask.title || '（无标题）' }}</p>
        <p class="reg-sheet__skills">
          <template v-if="(completingTask.skills || []).length">
            关联技能：{{ (completingTask.skills || []).join('、') }}
          </template>
          <template v-else>
            这条任务没有关联技能 —— 提交只会留下一条完成记录，不会带来技能升级。
          </template>
        </p>

        <div v-if="completingCriteria" class="reg-sheet__criteria">
          <span>{{ completingCriteria.label }}</span>
          <p>{{ completingCriteria.text }}</p>
        </div>

        <div class="reg-sheet__field">
          <label for="tv-evidence">
            实践证据
            <small>
              <template v-if="completingCriteria">
                照上面的{{ completingCriteria.label }}，写你实际做了什么、留下了什么
              </template>
              <template v-else>具体做了什么、有什么产出</template>
            </small>
          </label>
          <textarea
            id="tv-evidence"
            v-model="evidenceText"
            rows="6"
            placeholder="例：把登录和打卡两个页面搭完了，用 10 条真实数据自测通过，没有报错"
          />
          <div class="reg-sheet__count">
            {{ evidenceText.trim().length }} / {{ EVIDENCE_MAX_LENGTH }}
          </div>
        </div>

        <div v-if="evidenceError" class="notice notice-warn">{{ evidenceError }}</div>
        <div v-if="submitError" class="notice notice-danger">{{ submitError }}</div>

        <p class="reg-sheet__note">
          <template v-if="(completingTask.skills || []).length">
            提交后会同时得到三样东西：<strong>任务完成记录</strong>（真正落盘）、
            <strong>成长成果</strong>（可能构不成）、<strong>技能升级预览</strong>（不会立刻写入成长历史）。
          </template>
          <template v-else>
            这条提交只会留下一份<strong>任务完成记录</strong>（真正落盘），不会有成长成果，也不会有升级预览。
          </template>
        </p>

        <div class="reg-sheet__foot">
          <button class="btn" :disabled="submitting" @click="closeComplete">取消</button>
          <button class="btn btn-primary" :disabled="submitting" @click="submit">
            <span v-if="submitting" class="spinner" />
            {{ submitting ? '提交中…' : '确认提交' }}
          </button>
        </div>
      </section>
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
    </Teleport>
  </div>
</template>
