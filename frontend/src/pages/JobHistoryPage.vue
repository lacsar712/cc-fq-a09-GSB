<template>
  <q-page class="page-pad">
    <div class="row items-center q-mb-md">
      <div class="text-h5">作业历史</div>
      <q-space />
      <q-btn flat icon="refresh" label="刷新" @click="reloadAll" :loading="loading" />
      <q-btn
        v-if="auth.role === 'bioops'"
        color="primary"
        class="q-ml-sm"
        label="新建作业"
        to="/jobs/new"
      />
    </div>

    <!-- 标记操作区：过滤 + 落库说明（运维可挂标，审计员只看） -->
    <q-card flat bordered class="q-mb-md">
      <q-card-section class="q-pb-sm">
        <div class="text-subtitle1">标记操作区</div>
        <div class="text-caption text-grey-7">
          运维（bioops）可在每行「标记」按钮给作业挂多个标记，审计员只读。
          按单个标记收缩历史时请求直接打到服务端：<code>GET /api/jobs?tag=&lt;标记&gt;</code>，前端不做本地筛选。
        </div>
      </q-card-section>
      <q-card-section class="row items-center q-gutter-sm q-pt-xs">
        <q-select
          v-model="filterTag"
          :options="tagOptions"
          option-label="name"
          option-value="name"
          emit-value
          map-options
          clearable
          outlined
          dense
          label="按标记收缩（服务端过滤）"
          style="min-width: 280px"
          :loading="tagsLoading"
          @update:model-value="applyFilter"
        >
          <template #option="{ itemProps, opt }">
            <q-item v-bind="itemProps">
              <q-item-section>{{ opt.name }}</q-item-section>
              <q-item-section side class="text-grey-6">{{ opt.job_count }} 个作业</q-item-section>
            </q-item>
          </template>
          <template #no-option>
            <q-item><q-item-section class="text-grey-6">暂无任何标记</q-item-section></q-item>
          </template>
        </q-select>
        <q-chip
          v-if="activeTag"
          color="primary"
          text-color="white"
          icon="filter_alt"
          removable
          @remove="clearFilter"
        >
          已按标记收缩：{{ activeTag }}
        </q-chip>
        <div v-else class="text-grey-6">未按标记过滤，展示全部历史</div>
      </q-card-section>
      <q-separator />
      <q-card-section class="q-py-sm">
        <div class="text-caption text-grey-8">
          <b>标记如何落库：</b>标记保存在 PostgreSQL <code>job_tags</code> 表
          （字段 <code>job_id</code> / <code>tag</code> / <code>created_by</code> / <code>created_at</code>，
          <code>(job_id, tag)</code> 唯一约束，作业删除时级联清理）。
          保存走 <code>PUT /api/jobs/{id}/tags</code> 整体替换该作业的全部标记；
          列表收缩走 <code>GET /api/jobs?tag=…</code> 由后端 SQL 过滤后返回。
        </div>
      </q-card-section>
    </q-card>

    <q-table
      flat
      bordered
      row-key="id"
      :rows="rows"
      :columns="columns"
      :loading="loading"
      hide-pagination
      :pagination="{ rowsPerPage: 0 }"
    >
      <template #body-cell-status="props">
        <q-td :props="props">
          <q-badge :color="statusColor(props.row.status)">
            {{ statusLabel(props.row.status) }}
          </q-badge>
        </q-td>
      </template>
      <template #body-cell-tags="props">
        <q-td :props="props">
          <template v-if="props.row.tags && props.row.tags.length">
            <q-chip
              v-for="t in props.row.tags"
              :key="t"
              dense
              color="blue-1"
              text-color="primary"
              class="q-mr-xs"
            >
              {{ t }}
            </q-chip>
          </template>
          <span v-else class="text-grey-5">—</span>
        </q-td>
      </template>
      <template #body-cell-metrics="props">
        <q-td :props="props">
          <span v-if="props.row.metrics">
            Q={{ props.row.metrics.mean_quality ?? '—' }}
            · N={{ props.row.metrics.n_rate ?? '—' }}
            · reads={{ props.row.metrics.reads ?? '—' }}
          </span>
          <span v-else class="text-grey-6">—</span>
        </q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props">
          <q-btn dense flat color="primary" label="详情" :to="`/jobs/${props.row.id}`" />
          <q-btn
            v-if="auth.role === 'bioops'"
            dense
            flat
            color="secondary"
            icon="sell"
            label="标记"
            @click="openTagEditor(props.row)"
          />
        </q-td>
      </template>
    </q-table>

    <tag-editor-dialog
      v-model="tagEditorOpen"
      :job="editingJob"
      :existing-tags="tagOptions"
      @saved="onTagsSaved"
    />
  </q-page>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { listJobs, listTags } from '../api/client'
import { useAuthStore } from '../stores/auth'
import TagEditorDialog from '../components/TagEditorDialog.vue'

const auth = useAuthStore()
const $q = useQuasar()
const loading = ref(false)
const tagsLoading = ref(false)
const rows = ref([])
const tagOptions = ref([])
const filterTag = ref(null)
const activeTag = ref(null)
const tagEditorOpen = ref(false)
const editingJob = ref(null)

const columns = [
  { name: 'id', label: 'ID', field: 'id', align: 'left' },
  { name: 'sample_name', label: '样例', field: 'sample_name', align: 'left' },
  { name: 'status', label: '状态', field: 'status', align: 'left' },
  { name: 'tags', label: '标记', field: 'tags', align: 'left' },
  { name: 'created_by', label: '提交人', field: 'created_by', align: 'left' },
  { name: 'metrics', label: '指标摘要', field: 'metrics', align: 'left' },
  {
    name: 'created_at',
    label: '创建时间',
    field: 'created_at',
    align: 'left',
    format: (v) => (v ? new Date(v).toLocaleString() : ''),
  },
  { name: 'actions', label: '操作', field: 'actions', align: 'left' },
]

function statusLabel(s) {
  return { pending: '排队中', running: '运行中', success: '成功', failed: '失败' }[s] || s
}

function statusColor(s) {
  return { pending: 'grey', running: 'info', success: 'positive', failed: 'negative' }[s] || 'grey'
}

async function load() {
  loading.value = true
  try {
    rows.value = await listJobs(activeTag.value)
  } catch (e) {
    $q.notify({ type: 'negative', message: e.message || '加载失败' })
  } finally {
    loading.value = false
  }
}

async function loadTags() {
  tagsLoading.value = true
  try {
    tagOptions.value = await listTags()
  } catch (e) {
    $q.notify({ type: 'negative', message: e.message || '标记列表加载失败' })
  } finally {
    tagsLoading.value = false
  }
}

function reloadAll() {
  load()
  loadTags()
}

function applyFilter(tag) {
  // 选中即收缩：带 ?tag= 重新请求服务端
  activeTag.value = tag || null
  load()
}

function clearFilter() {
  filterTag.value = null
  activeTag.value = null
  load()
}

function openTagEditor(job) {
  editingJob.value = job
  tagEditorOpen.value = true
}

function onTagsSaved() {
  // 标记落库后刷新历史与标记下拉（计数会变）
  reloadAll()
}

onMounted(reloadAll)
</script>
