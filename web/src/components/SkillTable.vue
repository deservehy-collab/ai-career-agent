<script setup>
import AgentTag from './AgentTag.vue'
import AppBadge from './AppBadge.vue'
import { levelTone } from '../utils/enums'

// user_skills 条目结构（agents/profile_agent.py）：{skill, level, evidence}
// level 是四档固定值：入门 / 初级 / 中级 / 高级
defineProps({
  skills: { type: Array, default: () => [] },
  strengths: { type: Array, default: () => [] },
  weaknesses: { type: Array, default: () => [] },
  /** 可选的 Agent 归属标记（传节点名才显示） */
  agentNode: { type: String, default: '' },
})
</script>

<template>
  <section class="card">
    <div class="card-head">
      <h2>
        我的能力
        <span class="sub">Profile Agent 依据自述与项目经历分级</span>
      </h2>
      <div class="btn-row">
        <span class="badge">{{ skills.length }} 项</span>
        <AgentTag v-if="agentNode" :node="agentNode" />
      </div>
    </div>

    <div class="card-body">
      <div v-if="!skills.length" class="empty">没有解析出任何技能。</div>

      <div v-else class="table-wrap">
        <table class="data">
          <thead>
            <tr>
              <th style="width: 160px">技能</th>
              <th style="width: 90px">等级</th>
              <th>判断依据</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in skills" :key="item.skill">
              <td><strong>{{ item.skill }}</strong></td>
              <td><AppBadge :text="item.level" :tone="levelTone(item.level)" /></td>
              <td class="muted">{{ item.evidence || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="strengths.length || weaknesses.length" class="grid grid-2" style="margin-top: 16px">
        <div>
          <h3 style="font-size: 13px; color: var(--ok)">技术优势</h3>
          <ul style="margin: 6px 0 0; padding-left: 18px" class="muted">
            <li v-for="item in strengths" :key="item">{{ item }}</li>
            <li v-if="!strengths.length" class="faint" style="list-style: none; margin-left: -18px">
              未给出
            </li>
          </ul>
        </div>
        <div>
          <h3 style="font-size: 13px; color: var(--warn)">技术短板</h3>
          <ul style="margin: 6px 0 0; padding-left: 18px" class="muted">
            <li v-for="item in weaknesses" :key="item">{{ item }}</li>
            <li v-if="!weaknesses.length" class="faint" style="list-style: none; margin-left: -18px">
              未给出
            </li>
          </ul>
        </div>
      </div>
    </div>
  </section>
</template>
