<template>
  <q-dialog :model-value="modelValue" @update:model-value="emit('update:modelValue', $event)">
    <q-card style="min-width: 460px">
      <q-card-section>
        <div class="text-h6">编辑标记 · 作业 #{{ job?.id }}</div>
        <div class="text-caption text-grey-7 q-mt-xs">
          一个作业可挂多个标记；输入新名称回车即创建。保存时整体替换并落库
          （PUT /api/jobs/{{ job?.id }}/tags → job_tags 表）。
        </div>
      </q-card-section>

      <q-card-section class="q-pt-none">
        <q-select
          v-model="selected"
          :options="options"
          label="标记（如 night-qc）"
          hint="字母/数字开头，可含 . _ -，最长 32 字符；最多 8 个"
          outlined
          dense
          multiple
          use-chips
          use-input
          input-debounce="0"
          new-value-mode="add-unique"
          :disable="saving"
          @new-value="onNewValue"
        />
      </q-card-section>

      <q-card-actions align="right">
        <q-btn flat label="取消" :disable="saving" @click="emit('update:modelValue', false)" />
        <q-btn color="primary" label="保存落库" :loading="saving" @click="save" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { setJobTags } from '../api/client'

const TAG_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$/
const MAX_TAGS = 8

const props = defineProps({
  modelValue: Boolean,
  job: { type: Object, default: null },
  // 已存在的标记（[{ name, job_count }]），作为下拉候选
  existingTags: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'saved'])

const $q = useQuasar()
const selected = ref([])
const options = ref([])
const saving = ref(false)

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    selected.value = [...(props.job?.tags || [])]
    options.value = props.existingTags.map((t) => t.name)
  },
)

function onNewValue(val, done) {
  const name = String(val || '').trim()
  if (!TAG_RE.test(name)) {
    $q.notify({ type: 'warning', message: `标记名不合法：${val}（字母/数字开头，可含 . _ -，最长 32 字符）` })
    return
  }
  done(name, 'add-unique')
}

async function save() {
  const names = selected.value.map((s) => String(s).trim()).filter(Boolean)
  const bad = names.find((n) => !TAG_RE.test(n))
  if (bad) {
    $q.notify({ type: 'warning', message: `标记名不合法：${bad}` })
    return
  }
  if (names.length > MAX_TAGS) {
    $q.notify({ type: 'warning', message: `单个作业最多 ${MAX_TAGS} 个标记` })
    return
  }
  saving.value = true
  try {
    const job = await setJobTags(props.job.id, names)
    $q.notify({
      type: 'positive',
      message: job.tags.length ? `标记已落库：${job.tags.join('、')}` : '已清空该作业的全部标记',
    })
    emit('saved', job)
    emit('update:modelValue', false)
  } catch (e) {
    $q.notify({ type: 'negative', message: e.message || '保存失败' })
  } finally {
    saving.value = false
  }
}
</script>
