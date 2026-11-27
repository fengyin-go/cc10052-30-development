<template>
  <section class="sample-drift-panel" data-testid="sample-drift-panel">
    <div class="title-row">
      <div>
        <h3>样本量核对交接：领取分组漂移看板</h3>
        <p class="tip">样本核对批次按关联确认轮次领取数据；领取后固定实际采用的两份样本，来源再变化也能重开原申请。</p>
      </div>
      <button class="btn" type="button" data-testid="reload-applications" @click="loadApps()">刷新申请</button>
    </div>

    <div class="controls">
      <label>
        <span>核对申请</span>
        <select v-model="selectedId" data-testid="sample-app-select" @change="selectApp(selectedId)">
          <option value="">请选择</option>
          <option v-for="app in apps" :key="app.id" :value="app.id">
            {{ app.application_code }} · {{ app.实验编码 }} · {{ app.status }}
          </option>
        </select>
      </label>
      <label>
        <span>按编号/ID 重开原申请</span>
        <input v-model="lookupCode" placeholder="SR-T1T2-ORIG" data-testid="reopen-input" />
      </label>
      <button class="btn" type="button" data-testid="reopen-button" @click="reopen">重开原申请</button>
    </div>

    <form class="create-line" data-testid="sample-app-form" @submit.prevent="createApplication">
      <label><span>实验编码</span><input v-model="form.experiment_code" data-testid="sample-exp" /></label>
      <label><span>第一轮 ID</span><input v-model="form.left" data-testid="sample-left" /></label>
      <label><span>第二轮 ID</span><input v-model="form.right" data-testid="sample-right" /></label>
      <label><span>批次编号（可选）</span><input v-model="form.application_code" data-testid="sample-code" /></label>
      <button class="btn primary" type="submit" data-testid="create-sample-app">建立两份样本交接</button>
    </form>

    <p v-if="feedback" class="feedback" data-testid="sample-message">{{ feedback }}</p>
    <p v-if="error" class="error-text" data-testid="sample-error">{{ error }}</p>

    <div v-if="conflict" class="conflict-box" data-testid="claim-conflict">
      <h4>领取时发现两个版次冲突</h4>
      <p>{{ conflict.message }}</p>
      <div class="conflict-actions">
        <button class="btn" type="button" data-testid="claim-original" @click="claim('original')">
          采用原提交版 T2（原占比 0.6）
        </button>
        <button class="btn primary" type="button" data-testid="claim-corrected" @click="claim('corrected')">
          采用更正后 T2（更正占比 0.5）
        </button>
      </div>
      <div class="candidate-grid">
        <div v-for="(round, index) in conflict.original || []" :key="`co-${index}`">
          <strong>原版 {{ round.轮次 }}@v{{ round.版本 }}</strong>
          <span>实验组 {{ round.组内人数?.实验组 }} / 对照组 {{ round.组内人数?.对照组 }} / 占比 {{ round.ratio }}</span>
        </div>
        <div v-for="(round, index) in conflict.corrected || []" :key="`cc-${index}`">
          <strong>更正版 {{ round.轮次 }}@v{{ round.版本 }}</strong>
          <span>实验组 {{ round.组内人数?.实验组 }} / 对照组 {{ round.组内人数?.对照组 }} / 占比 {{ round.ratio }}</span>
        </div>
      </div>
    </div>

    <div v-if="app" class="app-card" data-testid="sample-app-detail">
      <header>
        <strong>{{ app.application_code }}</strong>
        <span>{{ app.status }}</span>
      </header>

      <section data-testid="adopted-samples">
        <h4>{{ app.adopted ? '实际采用的两份样本（已固定）' : '接手时将采用的两份样本' }}</h4>
        <div class="sample-grid">
          <article v-for="(round, index) in sampleRounds" :key="index" class="sample-card" :data-testid="`adopted-round-${index}`">
            <strong>{{ round.轮次 || round.round_code }}@v{{ round.版本 || round.version }}</strong>
            <p>实验组：{{ round.组内人数?.实验组 ?? round.counts?.实验组 ?? '—' }}</p>
            <p>对照组：{{ round.组内人数?.对照组 ?? round.counts?.对照组 ?? '—' }}</p>
            <p>实际占比：{{ round.ratio ?? '尚未取数' }}</p>
            <p v-if="round.缺组理由 || round.missing_reason" class="warning">{{ round.缺组理由 || round.missing_reason }}</p>
          </article>
        </div>
      </section>

      <div class="action-row">
        <button class="btn primary" type="button" data-testid="sample-claim" :disabled="app.adopted" @click="claim()">
          领取分组漂移看板数据
        </button>
        <button class="btn primary" type="button" data-testid="sample-review" :disabled="!app.adopted" @click="review">
          根据漂移看板复核
        </button>
        <button class="btn" type="button" data-testid="sample-trace" @click="trace">
          回查报告使用的轮次与组内人数
        </button>
        <button v-if="reviewResult" class="btn" type="button" data-testid="new-corrected-request" @click="startCorrectedRequest">
          办完核对：从更正后的 T2 发起新请求
        </button>
        <a class="btn" href="/aa_check" data-testid="reopen-aa-board">重新打开 AA 漂移看板</a>
      </div>

      <section v-if="reviewResult" class="review-box" data-testid="sample-review-result">
        <h4>复核结果</h4>
        <p>{{ reviewResult.message }}</p>
        <ul>
          <li v-for="item in reviewResult.ratio_checks || []" :key="item.round">
            {{ item.round }}：{{ item.available ? `${item.status}，占比 ${item.ratio}，偏移 ${item.offset}` : item.reason }}
          </li>
        </ul>
      </section>

      <section v-if="app.board?.diff" class="mini-board" data-testid="sample-board-diff">
        <h4>已领取漂移差异</h4>
        <p>
          新增 {{ app.board.diff.added?.length ?? 0 }} ·
          退出 {{ app.board.diff.exited?.length ?? 0 }} ·
          同一成员换组转换 {{ app.board.diff.transferred?.length ?? 0 }}
        </p>
        <p data-testid="sample-health">
          健康状态：{{ app.board.comparisons?.health?.健康状态变化 || '见看板健康度差异' }}
        </p>
      </section>
    </div>

    <section v-if="traceResult" class="trace-box" data-testid="trace-result">
      <h4>批次回查：报告使用轮次与组内人数</h4>
      <p>
        申请编号：{{ traceResult.application?.application_code }}；
        漂移请求：{{ traceResult.drift_request_id }}；
        报告：{{ traceResult.report_code || traceResult.report?.报告编码 || '复核后生成' }}
      </p>
      <table class="data-table">
        <thead>
          <tr><th>轮次</th><th>版本</th><th>实验组</th><th>对照组</th><th>实际占比</th></tr>
        </thead>
        <tbody>
          <tr v-for="(round, index) in traceResult.report_rounds || []" :key="index" data-testid="trace-round-row">
            <td>{{ round.轮次 || round.round }}</td>
            <td>{{ round.版本 || round.version }}</td>
            <td>{{ round.组内人数?.实验组 }}</td>
            <td>{{ round.组内人数?.对照组 }}</td>
            <td>{{ round.实际占比 }}</td>
          </tr>
        </tbody>
      </table>
      <p class="tip">重开路径：{{ traceResult.reopen?.path }}</p>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { driftClient } from '@/api/drift'

const apps = ref<any[]>([])
const selectedId = ref<number | string>('')
const app = ref<any>(null)
const conflict = ref<any>(null)
const feedback = ref('')
const error = ref('')
const lookupCode = ref('SR-T1T2-ORIG')
const reviewResult = ref<any>(null)
const traceResult = ref<any>(null)
const form = ref({ experiment_code: 'EXP-T1T2', left: '1', right: '2', application_code: '' })

const sampleRounds = computed<any[]>(() => {
  if (!app.value) return []
  return app.value.adopted_rounds || app.value.pinned || []
})

async function loadApps(selectFirst = true) {
  const result = await driftClient.applications()
  if (!result.ok) {
    error.value = result.message || '申请列表读取失败'
    return
  }
  apps.value = result.items || []
  if (selectFirst && apps.value.length) {
    selectedId.value = apps.value[0].id
    await selectApp(selectedId.value)
  }
}

async function selectApp(id: number | string) {
  if (!id) return
  conflict.value = null
  reviewResult.value = null
  traceResult.value = null
  error.value = ''
  const result = await driftClient.application(id)
  if (!result.ok) {
    error.value = result.message || '原申请读取失败'
    app.value = null
    return
  }
  app.value = result.application
}

async function reopen() {
  if (!lookupCode.value) return
  const result = await driftClient.application(lookupCode.value)
  if (!result.ok) {
    error.value = result.message || '原申请不存在'
    return
  }
  selectedId.value = result.application.id
  await selectApp(result.application.id)
  feedback.value = '已重开原申请；以下为当时固定的两份样本'
}

async function claim(resolution?: string) {
  if (!selectedId.value) return
  error.value = ''
  feedback.value = ''
  const result = await driftClient.claim(selectedId.value, resolution)
  if (result.conflict || result.status === 409) {
    conflict.value = result
    if (result.application) app.value = result.application
    return
  }
  if (!result.ok) {
    error.value = result.message || '领取失败'
    return
  }
  conflict.value = null
  app.value = result.application
  feedback.value = result.message
  await loadApps(false)
}

async function review() {
  if (!selectedId.value) return
  const result = await driftClient.review(selectedId.value)
  if (!result.ok && !result.review) {
    error.value = result.message || '复核失败'
    return
  }
  reviewResult.value = result.review
  feedback.value = result.message
  app.value = result.application
}

async function trace() {
  if (!selectedId.value) return
  const result = await driftClient.trace(selectedId.value)
  if (!result.ok) {
    error.value = result.message || '回查失败'
    return
  }
  traceResult.value = result
  feedback.value = '已回查报告可使用的轮次与组内人数'
}

async function createApplication() {
  error.value = ''
  const roundIds = [form.value.left, form.value.right].filter(Boolean).map((value) => Number(value) || value)
  const result = await driftClient.createApplication({
    experiment_code: form.value.experiment_code,
    application_code: form.value.application_code || undefined,
    round_ids: roundIds,
  })
  if (!result.ok) {
    error.value = result.message || '建立交接失败'
    return
  }
  feedback.value = result.message
  await loadApps(false)
  selectedId.value = result.application.id
  await selectApp(result.application.id)
}

async function startCorrectedRequest() {
  if (!app.value) return
  error.value = ''
  feedback.value = ''
  const firstRoundId = app.value.pinned?.[0]?.round_id || app.value.adopted_rounds?.[0]?.round_id || 1
  const created = await driftClient.createApplication({
    experiment_code: app.value.实验编码,
    application_code: `SR-CORRECTED-${Date.now()}`,
    round_ids: [firstRoundId, 'T2'],
  })
  if (!created.ok) {
    error.value = created.message || '更正后请求建立失败'
    return
  }
  selectedId.value = created.application.id
  const claimed = await driftClient.claim(created.application.id)
  if (!claimed.ok) {
    error.value = claimed.message || '更正后样本领取失败'
    app.value = created.application
    return
  }
  app.value = claimed.application
  feedback.value = `新请求已采用更正后的 T2；${claimed.message}`
  await loadApps(false)
}

onMounted(() => loadApps())
</script>

<style scoped>
.sample-drift-panel { background: #fff; border: 1px solid var(--border, #e4e7ec); border-radius: 10px; padding: 16px; margin: 14px 0; }
.title-row, .controls, .action-row, .create-line { display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap; }
.title-row { justify-content: space-between; align-items: flex-start; }
.controls label, .create-line label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.controls input, .controls select, .create-line input { border: 1px solid #d0d5dd; border-radius: 6px; padding: 7px 9px; font: inherit; min-width: 210px; }
.create-line { margin: 12px 0; padding: 10px; background: #f9fafb; border-radius: 8px; }
.tip { color: #667085; font-size: 13px; margin: 4px 0; }
.feedback { background: #ecfdf3; border: 1px solid #abefc6; color: #067647; border-radius: 8px; padding: 10px; }
.error-text { color: #b42318; }
.conflict-box { background: #fffaeb; border: 1px solid #fedf89; border-radius: 8px; padding: 12px; margin: 12px 0; color: #b54708; }
.conflict-actions { display: flex; gap: 10px; flex-wrap: wrap; margin: 10px 0; }
.candidate-grid, .sample-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 8px; }
.candidate-grid div, .sample-card { background: #fff; border: 1px solid #eaecf0; border-radius: 8px; padding: 9px; display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.app-card { border-top: 1px solid #eaecf0; margin-top: 12px; padding-top: 12px; }
.app-card header { display: flex; justify-content: space-between; }
.action-row { margin: 12px 0; }
.review-box, .trace-box, .mini-board { border: 1px solid #eaecf0; border-radius: 8px; padding: 10px 12px; margin-top: 10px; }
.review-box { background: #f6fef9; }
.trace-box { background: #f9fafb; }
.warning { color: #b42318; }
button:disabled { opacity: .5; cursor: not-allowed; }
</style>
