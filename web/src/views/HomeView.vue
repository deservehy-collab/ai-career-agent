<script setup>
import { computed, onMounted, ref } from 'vue'

import AppBadge from '../components/AppBadge.vue'
import GrowthLoopDiagram from '../components/GrowthLoopDiagram.vue'

import { listJds } from '../api/endpoints'
import { useHealthStore } from '../stores/health'
import { useProfileStore } from '../stores/profile'
import { levelTone } from '../utils/enums'
import { formatDateTime, joinList } from '../utils/format'

/**
 * 职业成长首页。
 *
 * Hero 里的指标**全部来自真实接口**，逐个判断可用性：
 *   真实 JD   ← GET /api/knowledge/jds 的 count
 *   向量证据  ← GET /api/health 的 index.vectors（需 index.ok）
 *   技能标准  ← GET /api/health 的 knowledge.skills.count（需 skills.ok）
 *   项目模板  ← GET /api/health 的 knowledge.projects.count（需 projects.ok）
 *
 * 取不到就**整块隐藏**，绝不用写死的数字或 0 占位 —— 首页最容易被截图传播，
 * 编造的指标比没有指标更糟。全部取不到时给一句中性说明。
 */
const profile = useProfileStore()
const health = useHealthStore()

const jdCount = ref(null)
const jdFailed = ref(false)

onMounted(async () => {
  try {
    const payload = await listJds()
    if (typeof payload?.count === 'number') jdCount.value = payload.count
    else if (Array.isArray(payload?.jds)) jdCount.value = payload.jds.length
    else jdCount.value = null
  } catch {
    jdCount.value = null
    jdFailed.value = true
  }
})

/** 只收录"确实拿得到"的指标。 */
const metrics = computed(() => {
  const list = []
  const data = health.data

  if (jdCount.value !== null) {
    list.push({ key: 'jd', label: '真实 JD', value: jdCount.value, unit: '份' })
  }

  if (data?.index?.ok && typeof data.index.vectors === 'number') {
    list.push({ key: 'vectors', label: '向量证据', value: data.index.vectors, unit: '条' })
  }

  if (data?.knowledge?.skills?.ok && typeof data.knowledge.skills.count === 'number') {
    list.push({ key: 'skills', label: '技能标准', value: data.knowledge.skills.count, unit: '项' })
  }

  if (data?.knowledge?.projects?.ok && typeof data.knowledge.projects.count === 'number') {
    list.push({ key: 'projects', label: '项目模板', value: data.knowledge.projects.count, unit: '个' })
  }

  return list
})

const metricsUnavailable = computed(
  () => !health.loading && metrics.value.length === 0,
)

const displaySkills = computed(() => profile.lastSkills || [])
const isProfileEmpty = computed(
  () => !profile.major && !profile.grade && !profile.skills.length && !profile.targetJob,
)
</script>

<template>
  <div>
    <!-- Hero -->
    <section class="hero">
      <h1>AI Career Agent</h1>
      <p class="lead">
        大学生成长与就业智能规划系统。7 个专职 Agent 顺序协作，
        基于真实招聘 JD 的向量知识库（RAG）产出能力差距、学习路线与实战项目建议。
      </p>

      <div v-if="metrics.length" class="stat-row">
        <div v-for="item in metrics" :key="item.key" class="stat-tile">
          <div class="value">{{ item.value }}</div>
          <div class="label">{{ item.label }}（{{ item.unit }}）</div>
        </div>
      </div>

      <p v-else-if="metricsUnavailable" class="faint" style="margin-top: 18px; margin-bottom: 0">
        项目指标暂不可用（后端未连接或数据源缺失）。
        <router-link to="/status">查看系统状态</router-link>
      </p>

      <div class="hero-actions">
        <router-link class="btn btn-primary" to="/analyze">开始岗位分析 →</router-link>
        <router-link class="btn" to="/status">查看系统状态</router-link>
        <span>
          <AppBadge
            :text="health.unreachable ? '后端未连接' : health.status === 'ok' ? '系统就绪' : '降级运行'"
            :tone="health.unreachable ? 'danger' : health.status === 'ok' ? 'ok' : 'warn'"
          />
        </span>
      </div>

      <p v-if="jdFailed" class="faint" style="margin: 10px 0 0">
        岗位知识库统计读取失败，已隐藏该项指标。
      </p>
    </section>

    <!-- 核心业务路径 / 成长闭环（未实现环节如实标注） -->
    <GrowthLoopDiagram />

    <!-- 当前状态：画像 + 最近能力 -->
    <div class="grid grid-2">
      <section class="card" style="margin-bottom: 0">
        <div class="card-head">
          <h2>
            我的画像
            <span class="sub">保存在本机浏览器，分析时随请求提交</span>
          </h2>
          <AppBadge
            :text="isProfileEmpty ? '尚未填写' : '已保存'"
            :tone="isProfileEmpty ? 'warn' : 'ok'"
          />
        </div>
        <div class="card-body">
          <div v-if="isProfileEmpty" class="empty">
            还没有填写画像。<router-link to="/analyze">去填写</router-link>
          </div>
          <template v-else>
            <dl class="kv">
              <dt>专业</dt>
              <dd>{{ profile.major || '—' }}</dd>
              <dt>年级</dt>
              <dd>{{ profile.grade || '—' }}</dd>
              <dt>目标岗位</dt>
              <dd><strong>{{ profile.targetJob || '—' }}</strong></dd>
              <dt>自述技能</dt>
              <dd>{{ joinList(profile.skills, '未填写') }}</dd>
              <dt>项目经历</dt>
              <dd>{{ joinList(profile.projects, '未填写') }}</dd>
            </dl>
            <div class="btn-row" style="margin-top: 14px">
              <router-link class="btn" to="/analyze">编辑画像并分析</router-link>
            </div>
          </template>
        </div>
      </section>

      <section class="card" style="margin-bottom: 0">
        <div class="card-head">
          <h2>
            最近一次分析的能力表
            <span class="sub">与上面的自述技能分开保存</span>
          </h2>
          <span v-if="profile.lastSkillsAt" class="badge">
            更新于 {{ formatDateTime(profile.lastSkillsAt) }}
          </span>
        </div>
        <div class="card-body">
          <div v-if="!displaySkills.length" class="empty">
            还没有分析结果。完成一次<router-link to="/analyze">岗位分析</router-link>后，
            这里会保存结构化的能力表，供后续提交任务完成证据时使用。
          </div>
          <div v-else class="table-wrap">
            <table class="data">
              <thead>
                <tr>
                  <th style="width: 150px">技能</th>
                  <th style="width: 80px">等级</th>
                  <th>判断依据</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in displaySkills" :key="item.skill">
                  <td><strong>{{ item.skill }}</strong></td>
                  <td><AppBadge :text="item.level" :tone="levelTone(item.level)" /></td>
                  <td class="muted">{{ item.evidence || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>
