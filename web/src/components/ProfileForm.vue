<script setup>
import { computed, ref, watch } from 'vue'

import { useProfileStore } from '../stores/profile'
import { formatDateTime } from '../utils/format'
import { formatList, parseList } from '../utils/storage'

/**
 * 画像表单：直接编辑 profile store；store 内部已把改动写进 localStorage，
 * 所以这里不需要额外的"保存"按钮 —— 刷新页面内容还在。
 *
 * 技能 / 项目用多行文本编辑（用户写起来最自然），
 * 与 store 里的字符串数组之间来回转换：文本是输入时的真相，
 * 只有 store 被**外部**改动（如点"清空"）时才回灌文本。
 */
const profile = useProfileStore()

const skillsText = ref(formatList(profile.skills))
const projectsText = ref(formatList(profile.projects))

function sameList(a, b) {
  const left = a || []
  const right = b || []
  return left.length === right.length && left.every((item, i) => item === right[i])
}

watch(
  () => profile.skills,
  (value) => {
    // 解析后的结果和 store 一致就不动输入框，避免把用户正在敲的逗号/换行冲掉
    if (!sameList(parseList(skillsText.value), value)) skillsText.value = formatList(value)
  },
  { deep: true },
)

watch(
  () => profile.projects,
  (value) => {
    if (!sameList(parseList(projectsText.value), value)) projectsText.value = formatList(value)
  },
  { deep: true },
)

const skillCount = computed(() => profile.skills.length)
const projectCount = computed(() => profile.projects.length)

function onSkillsInput(event) {
  skillsText.value = event.target.value
  profile.skills = parseList(event.target.value)
}

function onProjectsInput(event) {
  projectsText.value = event.target.value
  profile.projects = parseList(event.target.value)
}

function handleClear() {
  if (!window.confirm('清空自述画像？已分析得到的能力表不会被删除。')) return
  profile.clearProfile()
  skillsText.value = ''
  projectsText.value = ''
}
</script>

<template>
  <section class="card">
    <div class="card-head">
      <h2>
        我的画像
        <span class="sub">保存在本机浏览器，每次分析随请求发送</span>
      </h2>
      <span v-if="profile.hasLastSkills" class="badge badge-primary">
        已有 {{ profile.lastSkills.length }} 项分析能力
      </span>
    </div>

    <div class="card-body">
      <div v-if="profile.storageFailed" class="notice notice-warn">
        浏览器本地存储不可用（可能是隐私模式或空间已满），画像这次没能保存，刷新后会丢失。
      </div>

      <div class="grid grid-2">
        <div>
          <div class="field">
            <label for="pf-major">专业</label>
            <input id="pf-major" v-model="profile.major" type="text" placeholder="如：计算机科学与技术" />
          </div>

          <div class="field">
            <label for="pf-grade">年级</label>
            <input id="pf-grade" v-model="profile.grade" type="text" placeholder="如：大三" />
          </div>

          <div class="field">
            <label for="pf-job">
              目标岗位
              <span class="hint">必填，后端要求非空</span>
            </label>
            <input
              id="pf-job"
              v-model="profile.targetJob"
              type="text"
              placeholder="如：AI应用开发工程师"
            />
          </div>
        </div>

        <div>
          <div class="field">
            <label for="pf-skills">
              自述技能
              <span class="hint">每行一项，或用顿号/逗号分隔 · 已填 {{ skillCount }} 项</span>
            </label>
            <textarea
              id="pf-skills"
              :value="skillsText"
              rows="5"
              placeholder="Python&#10;LangChain&#10;Docker"
              @input="onSkillsInput"
            />
          </div>

          <div class="field">
            <label for="pf-projects">
              项目经历
              <span class="hint">每行一项 · 已填 {{ projectCount }} 项</span>
            </label>
            <textarea
              id="pf-projects"
              :value="projectsText"
              rows="3"
              placeholder="RAG 知识库问答系统"
              @input="onProjectsInput"
            />
          </div>
        </div>
      </div>

      <div v-if="profile.profileWarnings.length" class="notice notice-info" style="margin-bottom: 0">
        画像还不完整（{{ profile.profileWarnings.join('、') }}）—— 仍可发起分析，
        但岗位匹配结果会偏保守。
      </div>

      <div class="btn-row" style="margin-top: 14px">
        <button class="btn" @click="handleClear">清空自述画像</button>
        <span v-if="profile.lastSkillsAt" class="faint">
          能力表更新于 {{ formatDateTime(profile.lastSkillsAt) }}
        </span>
      </div>
    </div>
  </section>
</template>
