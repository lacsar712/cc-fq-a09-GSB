<template>
  <div class="tag-cell">
    <q-chip
      v-for="t in tags"
      :key="t.name"
      dense
      square
      color="teal-1"
      text-color="teal-10"
      :icon="filterable ? 'label' : null"
      :removable="!readonly"
      remove-icon="close"
      class="tag-chip"
      @click="filterable && $emit('tag-click', t.name)"
      @remove="onRemove(t)"
    >
      {{ t.name }}
    </q-chip>

    <q-btn
      v-if="!readonly"
      flat
      dense
      size="sm"
      icon="add"
      label="标记"
      color="primary"
      @click="openAdd"
    >
      <q-menu v-model="menuOpen" :auto-close="false">
        <div style="min-width: 240px" class="q-pa-sm">
          <q-input
            v-model="draft"
            autofocus
            dense
            outlined
            label="标记名（小写/数字/-/_）"
            hint="如 night-qc；一个作业可挂多个"
            @keyup.enter="onAdd"
          >
            <template #append>
              <q-icon name="label" class="cursor-pointer" @click="onAdd" />
            </template>
          </q-input>
          <div class="row justify-end q-mt-sm">
            <q-btn flat dense label="取消" @click="menuOpen = false" />
            <q-btn dense color="primary" label="挂上" :loading="saving" @click="onAdd" />
          </div>
        </div>
      </q-menu>
    </q-btn>

    <span v-if="readonly && !tags.length" class="text-grey-6">—</span>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useQuasar } from 'quasar'
import { addJobTag, removeJobTag } from '../api/client'

const props = defineProps({
  tags: { type: Array, default: () => [] },
  jobId: { type: [Number, String], required: true },
  readonly: { type: Boolean, default: false },
  filterable: { type: Boolean, default: false },
})

const emit = defineEmits(['changed', 'tag-click'])

const $q = useQuasar()
const menuOpen = ref(false)
const draft = ref('')
const saving = ref(false)

const TAG_RE = /^[a-z0-9][a-z0-9\-_]{0,63}$/

function openAdd() {
  draft.value = ''
  menuOpen.value = true
}

async function onAdd() {
  const name = draft.value.trim().toLowerCase()
  if (!TAG_RE.test(name)) {
    $q.notify({ type: 'warning', message: '标记名仅允许小写字母、数字、- 与 _，且以字母/数字开头' })
    return
  }
  if (props.tags.some((t) => t.name === name)) {
    $q.notify({ type: 'warning', message: '该作业已挂此标记' })
    menuOpen.value = false
    return
  }
  saving.value = true
  try {
    await addJobTag(props.jobId, name)
    $q.notify({ type: 'positive', message: `已挂标记 ${name}` })
    menuOpen.value = false
    emit('changed')
  } catch (e) {
    $q.notify({ type: 'negative', message: e.message || '挂标记失败' })
  } finally {
    saving.value = false
  }
}

async function onRemove(tag) {
  $q.dialog({
    title: '摘除标记',
    message: `确认从作业 #${props.jobId} 摘除标记 “${tag.name}”？`,
    ok: { label: '摘除', color: 'negative' },
    cancel: { label: '取消', flat: true },
  }).onOk(async () => {
    try {
      await removeJobTag(props.jobId, tag.name)
      $q.notify({ type: 'positive', message: `已摘除 ${tag.name}` })
      emit('changed')
    } catch (e) {
      $q.notify({ type: 'negative', message: e.message || '摘除失败' })
    }
  })
}
</script>

<style scoped>
.tag-cell {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
}
.tag-chip {
  cursor: pointer;
}
</style>
