<script setup>
import { computed, onMounted } from 'vue'

import AppBadge from '../components/AppBadge.vue'
import { useHealthStore } from '../stores/health'
import { formatDateTime } from '../utils/format'
import { storeStatusText, storeStatusTone } from '../utils/enums'

/**
 * 系统状态页：直接展示 `GET /api/health` 的真实返回。
 * 四类依赖 —— Ollama / Chroma 索引 / 知识库 / 两个 store —— 逐项给出可达性与失败原因。
 */
const health = useHealthStore()

onMounted(() => {
  if (!health.data) health.refresh()
})

const data = computed(() => health.data)

/**
 * 后端理论上总会返回全部段落（backend/services.py::health），
 * 但字段缺失时**逐段降级**，不让整页崩掉，也不去猜缺失段落的状态。
 */
const SECTION_LABELS = {
  ollama: '本地模型服务',
  index: '向量索引',
  knowledge: '业务知识库',
  stores: '运行数据存储',
  config: '生效配置',
}

const missingSections = computed(() => {
  if (!data.value) return []
  return Object.entries(SECTION_LABELS)
    .filter(([key]) => !data.value[key])
    .map(([, label]) => label)
})

/** 整体「降级」时，把"哪些功能会受影响"讲清楚，而不是只说一句状态不好。 */
const degradedImpacts = computed(() => {
  const d = data.value
  if (!d || d.status === 'ok') return []
  const list = []
  if (!d.ollama?.ok) list.push('岗位分析无法执行（模型推理不可用）')
  else if (!d.ollama.chat_model_ready) list.push('缺少对话模型，分析会失败')
  else if (!d.ollama.embedding_model_ready) list.push('缺少嵌入模型，岗位检索会失败')
  if (!d.index?.ok) list.push('岗位知识库检索会降级为「无证据」（分析仍可继续）')
  if (d.knowledge?.skills && !d.knowledge.skills.ok) list.push('技能前置门禁不会执行，升级判定偏宽松')
  if (d.knowledge?.projects && !d.knowledge.projects.ok) list.push('项目推荐可能为空')
  if (d.stores?.growth && !d.stores.growth.writable) list.push('成长历史不可写，成长记录无法更新')
  if (d.stores?.loop && !d.stores.loop.writable) list.push('任务记录不可写，任务完成无法登记')
  return list
})
</script>

<template>
  <div>
    <div class="page-head">
      <h1>系统状态</h1>
      <p>后端 /api/health 的实时结果。任一依赖不可用都会在这里说明原因。</p>
    </div>

    <section class="card">
      <div class="card-head">
        <h2>
          总体状态
          <span class="sub">
            {{ health.fetchedAt ? `检查于 ${formatDateTime(health.fetchedAt)}` : '尚未检查' }}
          </span>
        </h2>
        <div class="btn-row">
          <AppBadge
            v-if="data"
            :text="data.status === 'ok' ? '正常' : '降级运行'"
            :tone="data.status === 'ok' ? 'ok' : 'warn'"
          />
          <AppBadge v-else :text="health.loading ? '检查中…' : '不可达'" :tone="health.unreachable ? 'danger' : 'muted'" />
          <button class="btn" :disabled="health.loading" @click="health.refresh()">
            {{ health.loading ? '检查中…' : '重新检查' }}
          </button>
        </div>
      </div>

      <div class="card-body">
        <div v-if="health.errorMessage && !data" class="notice notice-danger">
          <strong>无法连接后端</strong>
          <div style="margin-top: 4px">{{ health.errorMessage }}</div>
        </div>

        <div v-else-if="health.loading && !data" class="empty">正在检查系统状态…</div>

        <div v-else-if="missingSections.length" class="notice notice-warn" style="margin-bottom: 0">
          后端体检结果缺少以下段落：<strong>{{ missingSections.join('、') }}</strong>。
          对应区块已隐藏 —— 缺失不等于正常，也不等于异常，这里不做推测。
        </div>

        <div v-else-if="degradedImpacts.length" class="notice notice-warn" style="margin-bottom: 0">
          <strong>「降级运行」意味着部分功能受影响：</strong>
          <ul>
            <li v-for="(item, i) in degradedImpacts" :key="i">{{ item }}</li>
          </ul>
        </div>
      </div>
    </section>

    <template v-if="data">
      <!-- Ollama -->
      <section v-if="data.ollama" class="card">
        <div class="card-head">
          <h2>本地模型服务（Ollama）</h2>
          <AppBadge
            :text="data.ollama.ok ? '可达' : '不可达'"
            :tone="data.ollama.ok ? 'ok' : 'danger'"
          />
        </div>
        <div class="card-body">
          <dl class="kv">
            <dt>服务地址</dt>
            <dd class="mono">{{ data.ollama.base_url }}</dd>
            <dt>对话模型</dt>
            <dd>
              <code class="mono">{{ data.ollama.chat_model }}</code>
              <AppBadge
                :text="data.ollama.chat_model_ready ? '已安装' : '未安装'"
                :tone="data.ollama.chat_model_ready ? 'ok' : 'danger'"
              />
            </dd>
            <dt>嵌入模型</dt>
            <dd>
              <code class="mono">{{ data.ollama.embedding_model }}</code>
              <AppBadge
                :text="data.ollama.embedding_model_ready ? '已安装' : '未安装'"
                :tone="data.ollama.embedding_model_ready ? 'ok' : 'danger'"
              />
            </dd>
            <dt>已安装模型</dt>
            <dd>
              <div v-if="data.ollama.models?.length" class="tags">
                <span v-for="name in data.ollama.models" :key="name" class="badge mono">{{ name }}</span>
              </div>
              <span v-else class="faint">未读取到模型列表</span>
            </dd>
            <dt v-if="data.ollama.error">错误</dt>
            <dd v-if="data.ollama.error" class="mono" style="color: var(--danger)">
              {{ data.ollama.error }}
            </dd>
          </dl>
        </div>
      </section>

      <!-- 索引 + 知识库 -->
      <div class="grid grid-2">
        <section v-if="data.index" class="card" style="margin-bottom: 0">
          <div class="card-head">
            <h2>向量索引（Chroma）</h2>
            <AppBadge :text="data.index.ok ? '正常' : '异常'" :tone="data.index.ok ? 'ok' : 'danger'" />
          </div>
          <div class="card-body">
            <dl class="kv">
              <dt>索引文件</dt>
              <dd class="mono">{{ data.index.path }}</dd>
              <dt>文件存在</dt>
              <dd>{{ data.index.exists ? '是' : '否' }}</dd>
              <dt>Collection</dt>
              <dd>{{ data.index.collections ?? '—' }}</dd>
              <dt>向量条数</dt>
              <dd>{{ data.index.vectors ?? '—' }}</dd>
              <dt v-if="data.index.error">错误</dt>
              <dd v-if="data.index.error" class="mono" style="color: var(--danger)">
                {{ data.index.error }}
              </dd>
            </dl>
            <p class="faint" style="margin-bottom: 0">
              索引缺失时检索会降级为"无证据"，但分析流程仍会继续。
            </p>
          </div>
        </section>

        <section v-if="data.knowledge" class="card" style="margin-bottom: 0">
          <div class="card-head">
            <h2>业务知识库</h2>
            <AppBadge
              :text="data.knowledge.skills.ok && data.knowledge.projects.ok ? '正常' : '异常'"
              :tone="data.knowledge.skills.ok && data.knowledge.projects.ok ? 'ok' : 'danger'"
            />
          </div>
          <div class="card-body">
            <dl class="kv">
              <dt>技能库</dt>
              <dd>
                <AppBadge
                  :text="data.knowledge.skills.ok ? `${data.knowledge.skills.count} 项技能` : '加载失败'"
                  :tone="data.knowledge.skills.ok ? 'ok' : 'danger'"
                />
                <div v-if="data.knowledge.skills.error" class="mono" style="color: var(--danger)">
                  {{ data.knowledge.skills.error }}
                </div>
              </dd>
              <dt>项目库</dt>
              <dd>
                <AppBadge
                  :text="data.knowledge.projects.ok ? `${data.knowledge.projects.count} 个项目` : '加载失败'"
                  :tone="data.knowledge.projects.ok ? 'ok' : 'danger'"
                />
                <div v-if="data.knowledge.projects.error" class="mono" style="color: var(--danger)">
                  {{ data.knowledge.projects.error }}
                </div>
              </dd>
            </dl>
            <p class="faint" style="margin-bottom: 0">
              技能库用于成长升级的前置门禁，项目库用于项目推荐排序。
            </p>
          </div>
        </section>
      </div>

      <!-- 存储 -->
      <section v-if="data.stores" class="card" style="margin-top: 16px">
        <div class="card-head">
          <h2>
            运行数据存储
            <span class="sub">runs/ 目录，属于本机状态，不入库</span>
          </h2>
        </div>
        <div class="card-body">
          <div class="table-wrap">
            <table class="data">
              <thead>
                <tr>
                  <th style="width: 130px">文件</th>
                  <th style="width: 90px">状态</th>
                  <th style="width: 100px">可写</th>
                  <th style="width: 90px">已存在</th>
                  <th>路径 / 说明</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td><strong>成长历史</strong><div class="faint">growth.json</div></td>
                  <td>
                    <AppBadge
                      :text="storeStatusText(data.stores.growth.status)"
                      :tone="storeStatusTone(data.stores.growth.status)"
                    />
                  </td>
                  <td>{{ data.stores.growth.writable ? '是' : '否' }}</td>
                  <td>{{ data.stores.growth.exists ? '是' : '否' }}</td>
                  <td>
                    <div class="mono faint">{{ data.stores.growth.path }}</div>
                    <div v-if="data.stores.growth.warning" style="color: var(--warn)">
                      {{ data.stores.growth.warning }}
                    </div>
                  </td>
                </tr>
                <tr>
                  <td>
                    <strong>任务记录</strong>
                    <div class="faint">
                      loop.json · {{ data.stores.loop.rounds }} 轮
                    </div>
                  </td>
                  <td>
                    <AppBadge
                      :text="storeStatusText(data.stores.loop.status)"
                      :tone="storeStatusTone(data.stores.loop.status)"
                    />
                  </td>
                  <td>{{ data.stores.loop.writable ? '是' : '否' }}</td>
                  <td>{{ data.stores.loop.exists ? '是' : '否' }}</td>
                  <td>
                    <div class="mono faint">{{ data.stores.loop.path }}</div>
                    <div v-if="data.stores.loop.warning" style="color: var(--warn)">
                      {{ data.stores.loop.warning }}
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <!-- 配置 -->
      <section v-if="data.config" class="card">
        <div class="card-head">
          <h2>
            生效配置
            <span class="sub">来自后端 backend/config.py</span>
          </h2>
        </div>
        <div class="card-body">
          <dl class="kv">
            <dt>对话模型</dt>
            <dd class="mono">{{ data.config.chat_model }}</dd>
            <dt>嵌入模型</dt>
            <dd class="mono">{{ data.config.embedding_model }}</dd>
            <dt>运行数据目录</dt>
            <dd class="mono">{{ data.config.runs_dir }}</dd>
            <dt>后台并发上限</dt>
            <dd>
              {{ data.config.task_workers }}
              <span class="faint"
                >（固定为 1：运行数据的读—改—写只在进程内串行安全，服务必须以单 worker 启动）</span
              >
            </dd>
          </dl>
        </div>
      </section>
    </template>
  </div>
</template>
