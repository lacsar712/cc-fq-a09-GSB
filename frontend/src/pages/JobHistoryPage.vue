<template>
  <q-page class="page-pad">
    <div class="row items-center q-mb-md">
      <div class="text-h5">作业历史</div>
      <q-space />
      <q-btn flat icon="refresh" label="刷新" @click="load" :loading="loading" />
      <q-btn
        v-if="auth.role === 'bioops'"
        color="primary"
        class="q-ml-sm"
        label="新建作业"
        to="/jobs/new"
      />
    </div>

    <!-- 标记操作区：点标记即在服务端按该标记收缩历史 -->
    <q-card flat bordered class="q-mb-md">
      <q-card-section class="q-pa-md">
        <div class="row items-center q-gutter-sm flex-wrap">
          <span class="text-subtitle2">标记筛选：</span>
          <q-btn
            :color="!activeTag ? 'primary' : 'grey-5'"
            :text-color="!activeTag ? 'white' : 'grey-9'"
            unelevated
            dense
            icon="inventory_2"
            label="全部作业"
            @click="selectTag(null)"
          />
          <q-btn
            v-for="t in allTags"
            :key="t"
            unelevated
            dense
            no-caps
            :color="activeTag === t ? 'teal' : 'teal-1'"
            :text-color="activeTag === t ? 'white' : 'teal-10'"
            :icon="activeTag === t ? 'label' : 'label_outline'"
            :label="t"
            @click="selectTag(t)"
          >
            <q-tooltip v-if="activeTag === t">再次点击或选「全部作业」取消收缩</q-tooltip>
          </q-btn>
          <span v-if="!allTags.length" class="text-grey-6 text-caption">
            还没有标记，{{ auth.role === 'bioops' ? '在下方作业行点「标记」即可挂载' : '运维挂载后此处可点选收缩' }}
          </span>
        </div>

        <q-banner v-if="activeTag" dense rounded class="bg-teal-1 text-teal-10 q-mt-sm" :inline-actions="false">
          <template #avatar><q-icon name="filter_alt" /></template>
          已在服务端按单标记 <b class="q-mx-xs">{{ activeTag }}</b> 收缩，仅返回挂有该标记的作业（共 {{ rows.length }} 条）。
          <template #action>
            <q-btn flat dense no-caps label="清除收缩" color="teal-10" @click="selectTag(null)" />
          </template>
        </q-banner>

        <div class="text-caption text-grey-7 q-mt-sm">
          <q-icon name="info" size="14px" />
          标记如何落库：每个标记是 <code>job_tags</code> 关联表中的一行（作业 ID + 标记名 + 挂载人），
          一个作业可挂多个标记；挂载 <code>PUT /api/jobs/&#123;id&#125;/tags</code>、摘除 <code>DELETE</code> 均由后端写库，
          列表筛选 <code>GET /api/jobs?tag=…</code> 在服务端完成（不是前端临时过滤）。
          仅运维（bioops）可增删，审计员（auditor）只读。
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
      <template #body-cell-tags="props">
        <q-td :props="props">
          <JobTags
            :tags="props.row.tags || []"
            :job-id="props.row.id"
            :readonly="auth.role !== 'bioops'"
            filterable
            @changed="load"
            @tag-click="selectTag"
          />
        </q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props">
          <q-btn dense flat color="primary" label="详情" :to="`/jobs/${props.row.id}`" />
        </q-td>
      </template>
    </q-table>
  </q-page>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { listJobs, listTags } from '../api/client'
import { useAuthStore } from '../stores/auth'
import JobTags from '../components/JobTags.vue'

const auth = useAuthStore()
const $q = useQuasar()
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const rows = ref([])
const allTags = ref([])
const activeTag = ref(route.query.tag ? String(route.query.tag) : null)

const columns = [
  { name: 'id', label: 'ID', field: 'id', align: 'left' },
  { name: 'sample_name', label: '样例', field: 'sample_name', align: 'left' },
  { name: 'status', label: '状态', field: 'status', align: 'left' },
  { name: 'created_by', label: '提交人', field: 'created_by', align: 'left' },
  { name: 'tags', label: '分类标记', field: 'tags', align: 'left' },
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
    // 服务端收缩：tag 作为查询参数发给后端，由数据库 join 过滤
    rows.value = await listJobs(activeTag.value || undefined)
    allTags.value = await listTags()
  } catch (e) {
    $q.notify({ type: 'negative', message: e.message || '加载失败' })
  } finally {
    loading.value = false
  }
}

function selectTag(name) {
  const target = name || null
  activeTag.value = activeTag.value === target ? null : target
  router.replace({ query: activeTag.value ? { tag: activeTag.value } : {} })
}

watch(activeTag, load)

onMounted(load)
</script>
