<script setup>
import { computed, ref } from 'vue'

/**
 * 认证页输入框：标签 + 内嵌图标 + 可显隐的密码 + hint 文案。
 * 登录/注册一共五处输入都用它，改样式只改这里。
 */
const props = defineProps({
  id: { type: String, required: true },
  label: { type: String, required: true },
  icon: { type: String, required: true }, // 24×24 单条 stroke 路径，沿用概览卡片那套图标语言
  modelValue: { type: String, default: '' },
  type: { type: String, default: 'text' }, // text | password
  placeholder: { type: String, default: '' },
  autocomplete: { type: String, default: 'off' },
  hint: { type: String, default: '' },
  maxlength: { type: [Number, String], default: undefined },
})

const emit = defineEmits(['update:modelValue'])

const revealed = ref(false)
const inputType = computed(() => (props.type === 'password' && !revealed.value ? 'password' : 'text'))
</script>

<template>
  <div class="field auth-field">
    <label :for="id">{{ label }}</label>
    <div class="auth-input-wrap">
      <svg
        class="auth-input-icon"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.8"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <path :d="icon" />
      </svg>
      <input
        :id="id"
        class="auth-input"
        :class="{ 'auth-input--password': type === 'password' }"
        :type="inputType"
        :value="modelValue"
        :placeholder="placeholder"
        :autocomplete="autocomplete"
        :maxlength="maxlength"
        :aria-describedby="hint ? `${id}-hint` : undefined"
        @input="emit('update:modelValue', $event.target.value)"
      />
      <button
        v-if="type === 'password'"
        class="auth-reveal"
        type="button"
        :aria-label="revealed ? '隐藏密码' : '显示密码'"
        :aria-pressed="revealed"
        @click="revealed = !revealed"
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12z" />
          <path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z" />
          <path v-if="revealed" d="M4 4l16 16" />
        </svg>
      </button>
    </div>
    <p v-if="hint" :id="`${id}-hint`" class="auth-hint">{{ hint }}</p>
  </div>
</template>
