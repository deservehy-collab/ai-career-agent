<script setup>
import { computed } from 'vue'

import AppBadge from '../components/AppBadge.vue'
import GrowthLoopDiagram from '../components/GrowthLoopDiagram.vue'

import { useProfileStore } from '../stores/profile'
import { levelTone } from '../utils/enums'
import { formatDateTime, joinList } from '../utils/format'

/**
 * 我的档案：只放"属于我自己"的东西 —— 画像、最近一次分析出的能力表、成长闭环。
 *
 * 原来这页顶部重复做了一遍概览页的 Hero 与四项知识库指标（同样请求
 * /api/knowledge/jds 与 /api/health），两个"首页"并排。指标归概览，
 * 本页改成纯本地档案视图，因此**不再发任何请求**（数据全在 profile store）。
 */
const profile = useProfileStore()

const displaySkills = computed(() => profile.lastSkills || [])
const isProfileEmpty = computed(
  () => !profile.major && !profile.grade && !profile.skills.length && !profile.targetJob,
)
</script>

<template>
  <div>
    <div class="page-head">
      <h1>我的档案</h1>
      <p>
        这台浏览器里保存的画像，与最近一次分析产出的结构化能力表。
        产品指标、七节点工作流与功能入口在<router-link to="/overview">概览</router-link>页。
      </p>
    </div>

    <!-- 成长闭环（未实现环节如实标注） -->
    <GrowthLoopDiagram />

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
