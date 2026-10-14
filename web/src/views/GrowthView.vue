<script setup>
import { computed, onMounted, ref } from 'vue'

import AgentTag from '../components/AgentTag.vue'
import AppBadge from '../components/AppBadge.vue'
import NextRoundResult from '../components/NextRoundResult.vue'

import { getGrowthHistory, getPending, startNextRound, addManualEvent } from '../api/endpoints'
import { pollRun } from '../composables/useRunPolling'
import { useProfileStore } from '../stores/profile'
import {
  gateStatusText,
  knowledgeBaseStatusText,
  storeStatusText,
  storeStatusTone,
} from '../utils/enums'
import { formatDateTime, joinList } from '../utils/format'

/**
 * 成长记录页。
 *
 * 三块数据各有出处，**不要混为一谈**：
 *   待处理成果 —— GET /api/growth/pending   （只读；还没交给成长节点的成果）
 *   成长历史   —— GET /api/growth/history   （只读；**真正落盘**的那份）
 *   下一轮生成 —— POST /api/growth/next-round（全系统**唯一**会写 runs/growth.json 的接口）
 *
 * 「下一轮」会重跑整条流水线（多次本地模型推理）并修改成长数据，因此：
 *   · 必须二次确认；
 *   · 必须携带真实画像（缺画像会让 profile 节点报错、该次 run 变 failed）；
 *   · 没有待处理成果时直接禁用，不做无意义的推理。
 */
const profile = useProfileStore()

const loading = ref(false)
const loadError = ref('')

const pending = ref(null)
const history = ref(null)

const confirming = ref(false)
const running = ref(false)
const runId = ref(null)
const runStatus = ref('idle')
const runResult = ref(null)
const runError = ref('')

const pendingEvents = computed(() => pending.value?.events || [])
const pendingTasks = computed(() => pending.value?.tasks || [])
const pendingWarnings = computed(() => pending.value?.warnings || [])
/** false 表示成长历史不可读、**无法判断哪些已处理** —— 是"判不了"，不是"没有待办"。 */
const pendingRestored = computed(() => pending.value?.restored !== false)

const historyEntries = computed(() => history.value?.history || [])
const latestSkills = computed(() => history.value?.latest_skills || [])
const baseline = computed(() => history.value?.baseline || null)

/** 画像至少要有点内容，否则等于让模型分析一个空白人。 */
const profileReady = computed(
  () => !!profile.major.trim() || !!profile.grade.trim() || profile.skills.length > 0 || profile.projects.length > 0,
)
const profileHint = computed(() => {
  if (profileReady.value) return ''
  return '画像为空：请先在「岗位分析」页填写专业 / 年级 / 技能，再生成下一轮。'
})

/** 没有待处理成果时禁用 —— 跑一次不会有任何变化，只是白白推理。 */
const canGenerate = computed(
  () => profileReady.value && pendingEvents.value.length > 0 && !running.value,
)

const blockedReason = computed(() => {
  if (running.value) return ''
  if (!pendingRestored.value) return '成长历史不可读，无法确认待处理成果是否完整，已禁用生成。'
  if (pendingEvents.value.length === 0) {
    return '当前没有「已完成但还没交给成长节点」的成果。先去「学习与项目」页提交任务完成证据。'
  }
  if (!profileReady.value) return profileHint.value
  return ''
})

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [pendingData, historyData] = await Promise.all([getPending(), getGrowthHistory()])
    pending.value = pendingData
    history.value = historyData
  } catch (error) {
    loadError.value = error?.message || '加载成长数据失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)

function askConfirm() {
  if (!canGenerate.value) return
  confirming.value = true
  runError.value = ''
  runResult.value = null
}

async function confirmGenerate() {
  if (!canGenerate.value || running.value) return

  confirming.value = false
  running.value = true
  runError.value = ''
  runResult.value = null
  runStatus.value = 'queued'

  const body = { user_profile: profile.toRequestProfile() }
  if (profile.targetJob.trim()) body.target_job = profile.targetJob.trim()

  try {
    const accepted = await startNextRound(body)
    runId.value = accepted.run_id
    runStatus.value = accepted.status || 'queued'

    const record = await pollRun(accepted.run_id, {
      onTick: (tick) => {
        runStatus.value = tick.status
      },
    })

    if (record.status === 'succeeded') {
      runResult.value = record.result || null
    } else {
      runError.value = record.error || '生成失败，但后端未给出错误信息。'
    }
    await load()
  } catch (error) {
    if (error?.name === 'AbortError') {
      runStatus.value = 'idle'
      return
    }
    runError.value = error?.message || '生成下一轮失败'
    runStatus.value = 'failed'
  } finally {
    running.value = false
  }
}

// ── 手动补录成果（打破空系统死锁）────────────────────────────────────────
const manual = ref({
  kind: 'learning',
  title: '',
  skills: '',
  evidence: '',
  open: false,
  submitting: false,
  message: '',
  error: '',
})

function toggleManual() {
  manual.value.open = !manual.value.open
  if (!manual.value.open) {
    manual.value.message = ''
    manual.value.error = ''
  }
}
function clearManualForm() {
  manual.value = { kind: 'learning', title: '', skills: '', evidence: '', open: false, submitting: false, message: '', error: '' }
}

async function submitManualEvent() {
  if (manual.value.submitting) return
  const title = manual.value.title.trim()
  const evidence = manual.value.evidence.trim()
  if (!title) {
    manual.value.error = '请填写成果标题'
    return
  }
  if (!evidence) {
    manual.value.error = '请填写成果证据（具体学了/做了什么）'
    return
  }

  manual.value.submitting = true
  manual.value.error = ''
  manual.value.message = ''
  try {
    const skills = manual.value.skills
      .split(/[\n,，、;；]/)
      .map((s) => s.trim())
      .filter(Boolean)
    const body = {
      kind: manual.value.kind,
      title,
      skills,
      evidence,
    }
    if (profile.targetJob.trim()) body.target_job = profile.targetJob.trim()
    await addManualEvent(body)
    manual.value.message = '成果已补录，将出现在上方待处理成果列表。'
    clearManualForm()
    await load()
  } catch (error) {
    const detail = error?.detail
    const reason =
      (detail && (detail.reason || detail.message)) ||
      error?.message ||
      '补录成果失败'
    manual.value.error = reason
  } finally {
    manual.value.submitting = false
  }
}
</script>

<template>
  <div>
    <div class="page-head">
      <h1>成长记录</h1>
      <p>
        查看已完成但尚未交接的成长成果、真正落盘的成长历史，
        并把新成果交给成长节点，生成下一轮学习与项目计划。
      </p>
    </div>

    <div v-if="loading && !pending && !history" class="card">
      <div class="card-body"><div class="empty">正在加载成长数据…</div></div>
    </div>

    <div v-else-if="loadError" class="notice notice-danger">
      <strong>加载成长数据失败</strong>
      <div style="margin-top: 4px">{{ loadError }}</div>
      <div style="margin-top: 8px"><button class="btn" @click="load">重试</button></div>
    </div>

    <template v-else>
      <!-- 待处理成果 -->
      <section class="card">
        <div class="card-head">
          <h2>
            待处理成长成果
            <span class="sub">已完成、但还没交给成长节点的成果</span>
          </h2>
          <div class="btn-row">
            <AppBadge
              :text="`${pendingEvents.length} 条`"
              :tone="pendingEvents.length ? 'warn' : 'ok'"
            />
            <AgentTag node="growth" />
            <button class="btn" :disabled="loading" @click="load">
              {{ loading ? '刷新中…' : '刷新' }}
            </button>
          </div>
        </div>

        <div class="card-body">
          <!-- 「判不了」与「没有」必须分开说 -->
          <div v-if="!pendingRestored" class="notice notice-warn">
            <strong>无法判断待处理成果</strong>
            <div style="margin-top: 4px">
              成长历史不可读，因此没法确定哪些成果已经处理过。为避免重复提交，本次不列出待处理成果。
              <ul style="margin: 6px 0 0; padding-left: 18px">
                <li v-for="(warn, i) in pendingWarnings" :key="i">{{ warn }}</li>
              </ul>
            </div>
          </div>

          <template v-else>
            <div v-if="!pendingEvents.length" class="empty">
              没有待处理成果。在「学习与项目」页<router-link to="/tasks">提交任务完成证据</router-link>后，
              成果会先出现在这里，再由下方按钮交给成长节点。
            </div>

            <div v-else>
              <article
                v-for="(event, i) in pendingEvents"
                :key="i"
                class="evidence-item"
                style="border-left-color: var(--agent-cognition)"
              >
                <header class="evidence-head">
                  <AppBadge
                    :text="event.type === 'project' ? '项目成果' : '学习成果'"
                    :tone="event.type === 'project' ? 'ok' : 'primary'"
                  />
                  <strong>{{ event.title }}</strong>
                  <span class="faint">{{ formatDateTime(event.at) }}</span>
                </header>
                <p class="evidence-quote" style="background: var(--agent-cognition-soft)">
                  {{ event.evidence || '（无证据）' }}
                </p>
                <div class="evidence-meta">
                  <span>涉及技能：{{ joinList(event.skills, '（未关联技能）') }}</span>
                  <span v-if="pendingTasks[i]" class="mono">
                    来源任务：{{ pendingTasks[i].task_id }}
                  </span>
                </div>
              </article>

              <p class="faint" style="margin: 12px 0 0">
                这些成果**还没有**进入成长历史。点击下方「生成下一轮」时，
                它们才会交给 growth_node 走正式写入路径并升级技能。
              </p>
            </div>

            <div v-for="(warn, i) in pendingWarnings" :key="i" class="notice notice-warn">{{ warn }}</div>
            <div v-if="pending?.skipped?.length" class="notice notice-info">
              有 {{ pending.skipped.length }} 条已完成任务无法构造成果（未填写证据等），可在「学习与项目」页查看。
            </div>
          </template>
        </div>
      </section>

      <!-- 手动补录成果（打破空系统死锁） -->
      <section class="card">
        <div class="card-head">
          <h2>
            手动补录成果
            <span class="sub">没有任务时也能录入一条自己学过/做过的成果（打破冷启动）</span>
          </h2>
          <button class="btn" @click="toggleManual">
            {{ manual.open ? '收起' : '补录一条成果' }}
          </button>
        </div>

        <div v-if="manual.open" class="card-body">
          <div class="notice notice-info">
            <strong>什么情况下用它？</strong>
            <div style="margin-top: 4px">
              当你还没有任何任务、想先记录一条实际学过的内容（比如学了 Git、做一个问答小项目），
              填好提交后它就会变成「待处理成果」，再点下方「生成下一轮」即可生成真正的学习与项目任务。
            </div>
          </div>

          <div
            v-if="manual.error"
            class="notice notice-danger"
            style="margin-top: 12px"
          >{{ manual.error }}</div>
          <div
            v-if="manual.message"
            class="notice notice-ok"
            style="margin-top: 12px"
          >{{ manual.message }}</div>

          <div style="margin-top: 14px; display: grid; gap: 14px">
            <div class="field">
              <label>成果类型</label>
              <div class="btn-row">
                <button
                  class="btn"
                  :class="manual.kind !== 'learning' && 'btn-ghost'"
                  :disabled="manual.submitting"
                  @click="manual.kind = 'learning'"
                >📖 学习成果</button>
                <button
                  class="btn"
                  :class="manual.kind !== 'project' && 'btn-ghost'"
                  :disabled="manual.submitting"
                  @click="manual.kind = 'project'"
                >🛠️ 项目成果</button>
              </div>
            </div>

            <div class="field">
              <label for="manual-title">成果标题</label>
              <input
                id="manual-title"
                v-model="manual.title"
                type="text"
                :disabled="manual.submitting"
                placeholder="如：完成 Git 版本控制入门 / 搭建了一个 RAG 问答小项目"
              />
            </div>

            <div class="field">
              <label for="manual-skills">
                涉及技能
                <span class="hint">多个用逗号或换行分隔，如：Git, Python</span>
              </label>
              <textarea
                id="manual-skills"
                v-model="manual.skills"
                :disabled="manual.submitting"
                rows="2"
                placeholder="Git，Docker"
              ></textarea>
            </div>

            <div class="field">
              <label for="manual-evidence">成果证据</label>
              <textarea
                id="manual-evidence"
                v-model="manual.evidence"
                :disabled="manual.submitting"
                rows="3"
                placeholder="具体学会了什么、做出了什么成果。例如：掌握了 clone/commit/push 等 Git 基本操作，并把本地项目推送到远程仓库。"
              ></textarea>
            </div>

            <div class="btn-row">
              <button
                class="btn btn-primary"
                :disabled="manual.submitting"
                @click="submitManualEvent"
              >
                <span v-if="manual.submitting" class="spinner" />
                {{ manual.submitting ? '提交中…' : '补录这条成果' }}
              </button>
              <button class="btn" :disabled="manual.submitting" @click="clearManualForm">清空</button>
            </div>
          </div>
        </div>
      </section>

      <!-- 生成下一轮 -->
      <section class="card">
        <div class="card-head">
          <h2>
            生成下一轮计划
            <span class="sub">把待处理成果正式写入成长历史，并重算学习与项目路线</span>
          </h2>
          <AppBadge
            :text="running ? '执行中' : canGenerate ? '可生成' : '已禁用'"
            :tone="running ? 'primary' : canGenerate ? 'ok' : 'muted'"
          />
        </div>

        <div class="card-body">
          <div v-if="blockedReason" class="notice notice-warn">{{ blockedReason }}</div>

          <div class="notice notice-danger">
            <strong>这是全系统唯一会写入成长数据的操作。</strong>
            它会重跑整条流水线（含多次本地模型推理，通常需要数十秒到数分钟），
            并把本轮成果正式写入 <span class="mono">runs/growth.json</span>。
          </div>

          <div class="btn-row">
            <button class="btn btn-primary" :disabled="!canGenerate" @click="askConfirm">
              <span v-if="running" class="spinner" />
              {{ running ? `执行中…（${runStatus}）` : '生成下一轮' }}
            </button>
            <span v-if="profileReady" class="faint">
              将携带画像：{{ profile.major || '未填专业' }} / {{ profile.grade || '未填年级' }} /
              {{ profile.skills.length }} 项技能
            </span>
          </div>

          <!-- 二次确认 -->
          <div v-if="confirming" class="notice notice-warn" style="margin-top: 14px">
            <strong>确认生成下一轮？</strong>
            <div style="margin-top: 4px">
              将把 <strong>{{ pendingEvents.length }} 条</strong>待处理成果交给成长节点，
              并重新生成学习与项目计划。该操作会修改 <span class="mono">runs/growth.json</span> 与
              <span class="mono">runs/loop.json</span>。
            </div>
            <div class="btn-row" style="margin-top: 10px">
              <button class="btn" @click="confirming = false">取消</button>
              <button class="btn btn-primary" @click="confirmGenerate">确认并开始</button>
            </div>
          </div>

          <div v-if="runError" class="notice notice-danger">{{ runError }}</div>

          <!-- 结果三态分离：任一项成功都不代表全部成功 -->
          <div v-if="runResult" style="margin-top: 14px">
            <NextRoundResult :result="runResult" />
          </div>
        </div>
      </section>

      <!-- 成长历史 -->
      <section class="card">
        <div class="card-head">
          <h2>
            成长历史
            <span class="sub">真正落盘到 runs/growth.json 的记录</span>
          </h2>
          <div class="btn-row">
            <AppBadge
              :text="`${history?.confirmed_count ?? 0} 次确认`"
              :tone="(history?.confirmed_count ?? 0) ? 'ok' : 'muted'"
            />
            <AppBadge
              v-if="history"
              :text="storeStatusText(history.status)"
              :tone="storeStatusTone(history.status)"
            />
          </div>
        </div>

        <div class="card-body">
          <div v-if="history && !history.writable" class="notice notice-warn">
            <strong>成长历史不可读</strong>
            <div style="margin-top: 4px">{{ history.warning }}</div>
          </div>

          <template v-else>
            <div v-if="!historyEntries.length" class="empty">
              还没有成长记录 —— 当前能力全部来自画像。
              提交任务完成证据并生成下一轮后，这里会出现第一条记录。
            </div>

            <div v-else>
              <div v-if="latestSkills.length" style="margin-bottom: 16px">
                <h3 style="font-size: 13px">最近一次确认的能力</h3>
                <div class="tags" style="margin-top: 8px">
                  <span v-for="item in latestSkills" :key="item.skill" class="badge badge-ok">
                    {{ item.skill }} · {{ item.level || '无' }}
                  </span>
                </div>
              </div>

              <article v-for="(entry, i) in historyEntries" :key="i" class="timeline-item">
                <div class="timeline-dot" />
                <div class="timeline-body">
                  <div class="timeline-head">
                    <strong>{{ formatDateTime(entry.at) }}</strong>
                    <span class="faint">{{ entry.target_job || '未记录目标岗位' }}</span>
                    <AppBadge
                      v-if="entry.knowledge_base_status"
                      :text="knowledgeBaseStatusText(entry.knowledge_base_status)"
                      :tone="entry.knowledge_base_status === 'ok' ? 'ok' : 'warn'"
                    />
                  </div>

                  <div v-if="(entry.level_changes || []).length" style="margin-top: 6px">
                    <ul style="margin: 0; padding-left: 18px" class="muted">
                      <li v-for="change in entry.level_changes" :key="change.skill">
                        <strong>{{ change.skill }}</strong>：{{ change.from || '无' }} → {{ change.to }}
                        <span class="faint">
                          （{{ gateStatusText(change.gate_status) }}
                          <template v-if="change.source"> · 来源：{{ change.source }}</template>）
                        </span>
                      </li>
                    </ul>
                  </div>
                  <p v-else class="faint" style="margin: 6px 0 0">本次没有技能等级变化。</p>

                  <div v-if="(entry.events || []).length" class="faint" style="margin-top: 6px">
                    关联成果：{{ joinList((entry.events || []).map((e) => e.title)) }}
                  </div>
                  <div v-if="(entry.blocked_upgrades || []).length" class="faint" style="margin-top: 4px">
                    被前置门禁拦下 {{ entry.blocked_upgrades.length }} 项
                  </div>
                </div>
              </article>
            </div>

            <dl v-if="baseline" class="kv" style="margin-top: 16px; grid-template-columns: 110px 1fr">
              <dt>能力基线来源</dt>
              <dd>{{ baseline.source || '（未记录）' }}</dd>
              <dt>基线建立时间</dt>
              <dd>{{ formatDateTime(baseline.at) }}</dd>
            </dl>
          </template>
        </div>
      </section>
    </template>
  </div>
</template>