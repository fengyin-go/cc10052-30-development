<template>
  <section class="drift-panel" data-testid="aa-drift-panel">
    <div class="panel-title-row">
      <div>
        <h3>AA 重跑轮次漂移看板（可选两轮）</h3>
        <p class="panel-tip">同一实验内选择一份或两份样本轮次，服务端核对组别、身份变化、缺组和撤销状态。</p>
      </div>
      <button class="btn" type="button" data-testid="toggle-round-setup" @click="showSetup = !showSetup">
        {{ showSetup ? '收起轮次构造' : '构造/更正轮次' }}
      </button>
    </div>

    <div v-if="showSetup" class="setup-grid">
      <form class="setup-card" data-testid="create-round-form" @submit.prevent="createRound">
        <h4>登记样本轮次</h4>
        <label><span>实验编码</span><input v-model="newRound.experiment_code" data-testid="round-exp" /></label>
        <label><span>轮次编码</span><input v-model="newRound.round_code" placeholder="T3" data-testid="round-code" /></label>
        <label><span>序号</span><input v-model.number="newRound.sequence" type="number" data-testid="round-sequence" /></label>
        <label class="inline"><input v-model="newRound.confirmed" type="checkbox" data-testid="round-confirmed" /> 正式确认</label>
        <label class="full"><span>成员（每行 u1:实验组）</span>
          <textarea v-model="newRound.membersText" rows="4" data-testid="round-members"></textarea>
        </label>
        <button class="btn primary" type="submit" data-testid="submit-round">新增样本轮次</button>
      </form>

      <form class="setup-card" data-testid="correct-form" @submit.prevent="correctAssignment">
        <h4>更正分组成员</h4>
        <label><span>实验编码</span><input v-model="correction.experiment_code" data-testid="correct-exp" /></label>
        <label><span>用户标识</span><input v-model="correction.user_id" data-testid="correct-user" /></label>
        <label><span>更正后组别</span>
          <select v-model="correction.to_group" data-testid="correct-group">
            <option>实验组</option>
            <option>对照组</option>
          </select>
        </label>
        <label><span>生成新版轮次</span><input v-model="correction.round_code" data-testid="correct-round" /></label>
        <label class="full"><span>更正原因</span><input v-model="correction.reason" data-testid="correct-reason" /></label>
        <button class="btn primary" type="submit" data-testid="submit-correction">登记更正并保留旧版</button>
      </form>
    </div>

    <div class="board-controls">
      <label>
        <span>实验编码</span>
        <input v-model="experimentCode" data-testid="drift-experiment" @change="loadRounds()" />
      </label>
      <label>
        <span>第一轮 / 基准轮</span>
        <select v-model="leftRoundId" data-testid="drift-left-round">
          <option value="">不选择</option>
          <option v-for="round in rounds" :key="`l-${round.id}`" :value="round.id">
            {{ round.round_code }}@v{{ round.version }} · {{ round.status }} · {{ round.total }}人
          </option>
        </select>
      </label>
      <label>
        <span>第二轮 / 重跑轮（可选）</span>
        <select v-model="rightRoundId" data-testid="drift-right-round">
          <option value="">不选择</option>
          <option v-for="round in rounds" :key="`r-${round.id}`" :value="round.id">
            {{ round.round_code }}@v{{ round.version }} · {{ round.status }} · {{ round.total }}人
          </option>
        </select>
      </label>
      <div class="control-buttons">
        <button class="btn" type="button" data-testid="select-original-t2" @click="selectT2(1)">原 T2（0.6）</button>
        <button class="btn" type="button" data-testid="select-corrected-t2" @click="selectT2(2)">更正 T2（0.5）</button>
        <button class="btn primary" type="button" data-testid="drift-compare" @click="compare">生成漂移看板</button>
        <button class="btn" type="button" data-testid="drift-save-request" @click="saveRequest">保存看板请求</button>
        <button class="btn primary" type="button" data-testid="drift-send-order" @click="sendOrder">按实际结果送出换组核对单</button>
      </div>
    </div>

    <div class="round-strip" data-testid="round-strip">
      <article v-for="round in rounds" :key="round.id" class="round-chip" :data-testid="`round-card-${round.id}`" :data-status="round.status">
        <header>
          <strong>{{ round.round_code }}@v{{ round.version }}</strong>
          <span class="badge" :data-revoked="round.revoked">{{ round.status }}</span>
        </header>
        <p>实验组 {{ round.counts?.实验组 ?? 0 }} · 对照组 {{ round.counts?.对照组 ?? 0 }}</p>
        <p v-if="round.ratio !== null && round.ratio !== undefined">实际占比：{{ round.ratio }}</p>
        <p v-if="round.missing_reason" class="warning" data-testid="round-missing-reason">{{ round.missing_reason }}</p>
        <p v-if="round.formal_reason" class="warning">{{ round.formal_reason }}</p>
        <div class="chip-actions">
          <button class="link" type="button" :data-testid="`confirm-round-${round.id}`" @click="changeRound(round.id, 'confirm')">正式确认</button>
          <button class="link danger" type="button" :data-testid="`revoke-round-${round.id}`" @click="changeRound(round.id, 'revoke')">撤销轮次</button>
        </div>
      </article>
    </div>

    <p v-if="feedback" class="panel-feedback" data-testid="aa-panel-message">{{ feedback }}</p>
    <p v-if="error" class="error-text" data-testid="aa-panel-error">{{ error }}</p>

    <div v-if="order" class="result-card" data-testid="transfer-order-result">
      <strong>{{ order.message }}</strong>
      <div v-if="order.order">核对单编号：<code>{{ order.order.order_code }}</code></div>
    </div>

    <div v-if="board" class="board-result" data-testid="drift-board" :data-comparable="String(board.formal_comparison_available)">
      <div class="basis-box" data-testid="actual-calculation">
        <strong>实际取数口径：</strong>{{ board.actual_calculation?.text || '本轮暂无实际占比' }}
      </div>

      <div v-if="board.unavailable_reasons?.length" class="unavailable-box" data-testid="drift-unavailable">
        <h4>哪些比较不可办理</h4>
        <ul>
          <li v-for="(reason, index) in board.unavailable_reasons" :key="index">{{ reason }}</li>
        </ul>
      </div>

      <div class="diff-grid">
        <section class="diff-card added" data-testid="drift-added">
          <h4>新增（{{ board.diff?.added?.length ?? 0 }}）</h4>
          <ul>
            <li v-for="item in board.diff?.added || []" :key="`add-${item.user_id}`">
              {{ item.user_id }} → {{ item.to_group }}
            </li>
            <li v-if="!(board.diff?.added?.length)" class="empty-inline">无</li>
          </ul>
        </section>
        <section class="diff-card exited" data-testid="drift-exited">
          <h4>退出（{{ board.diff?.exited?.length ?? 0 }}）</h4>
          <ul>
            <li v-for="item in board.diff?.exited || []" :key="`exit-${item.user_id}`">
              {{ item.user_id }}（原 {{ item.from_group }}）
            </li>
            <li v-if="!(board.diff?.exited?.length)" class="empty-inline">无</li>
          </ul>
        </section>
        <section class="diff-card transferred" data-testid="drift-transferred">
          <h4>只换组的同一成员（{{ board.diff?.transferred?.length ?? 0 }} 次转换）</h4>
          <ul>
            <li v-for="item in board.diff?.transferred || []" :key="`tr-${item.user_id}`">
              {{ item.user_id }}：{{ item.from_group }} → {{ item.to_group }}
            </li>
            <li v-if="!(board.diff?.transferred?.length)" class="empty-inline">无</li>
          </ul>
        </section>
      </div>

      <p v-if="board.diff?.summary?.计数口径" class="count-rule" data-testid="transition-count-rule">
        计数口径：{{ board.diff.summary.计数口径 }}
      </p>

      <section v-if="board.comparisons?.health?.available || board.comparisons?.health?.health_difference" class="health-box" data-testid="health-difference">
        <h4>健康度差异</h4>
        <p>占比变化：{{ board.comparisons.health.占比变化 || board.comparisons.health.health_difference?.占比变化 }}</p>
        <p>健康状态：{{ board.comparisons.health.健康状态变化 || board.comparisons.health.health_difference?.健康状态变化 }}</p>
        <p>健康度得分变化：{{ board.comparisons.health.health_score_delta ?? board.comparisons.health.health_difference?.health_score_delta }}</p>
      </section>

      <section v-if="board.adjacent_confirmed?.length" class="adjacent-box" data-testid="adjacent-confirmed">
        <h4>相邻已确认轮次排序（自动跳过撤销轮次）</h4>
        <ul>
          <li v-for="pair in board.adjacent_confirmed" :key="pair.index">
            {{ pair.statement }}
            <span v-if="pair.skipped_revoked?.length">；跳过撤销轮次：{{ pair.skipped_revoked.map((r: any) => r.round_code).join('、') }}</span>
          </li>
        </ul>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { driftClient } from '@/api/drift'

const experimentCode = ref('EXP-T1T2')
const rounds = ref<any[]>([])
const leftRoundId = ref<number | string>('')
const rightRoundId = ref<number | string>('')
const board = ref<any>(null)
const order = ref<any>(null)
const feedback = ref('')
const error = ref('')
const showSetup = ref(true)

const newRound = ref({
  experiment_code: 'EXP-T1T2',
  round_code: 'T3',
  sequence: 3,
  confirmed: true,
  membersText: 'u1:实验组\nu2:实验组\nu7:对照组\nu8:对照组',
})
const correction = ref({
  experiment_code: 'EXP-T1T2',
  user_id: 'u4',
  to_group: '对照组',
  round_code: 'T2',
  reason: '用户 u4 分组更正',
})

function parseMembers(text: string) {
  const trimmed = text.trim()
  if (!trimmed) return []
  if (trimmed.startsWith('[') || trimmed.startsWith('{')) return JSON.parse(trimmed)
  return trimmed.split(/\n|;|；/).map((line) => line.trim()).filter(Boolean).map((line) => {
    const [user_id, group] = line.split(/[:：,，]/).map((part) => part.trim())
    return { user_id, group }
  })
}

async function loadRounds(selectLatest = true) {
  error.value = ''
  const result = await driftClient.rounds(experimentCode.value)
  if (!result.ok) {
    error.value = result.message || '轮次读取失败'
    return
  }
  rounds.value = result.items || []
  if (selectLatest && rounds.value.length) {
    leftRoundId.value = rounds.value[0].id
    rightRoundId.value = rounds.value[rounds.value.length - 1].id
  }
}

function selectT2(version: number) {
  const target = rounds.value.find((round) => round.round_code === 'T2' && Number(round.version) === version)
  if (target) rightRoundId.value = target.id
  void compare()
}

async function compare() {
  feedback.value = ''
  error.value = ''
  order.value = null
  const result = await driftClient.board({
    experiment_code: experimentCode.value,
    left_round_id: leftRoundId.value,
    right_round_id: rightRoundId.value,
  })
  if (!result.ok) {
    error.value = result.message || '漂移看板生成失败'
    board.value = null
    return
  }
  board.value = result
  feedback.value = result.message
}

async function createRound() {
  error.value = ''
  feedback.value = ''
  try {
    const result = await driftClient.createRound({
      ...newRound.value,
      members: parseMembers(newRound.value.membersText),
    })
    if (!result.ok) throw new Error(result.message)
    feedback.value = result.message
    experimentCode.value = newRound.value.experiment_code
    await loadRounds(false)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '轮次登记失败'
  }
}

async function correctAssignment() {
  error.value = ''
  feedback.value = ''
  const result = await driftClient.correct(correction.value)
  if (!result.ok) {
    error.value = result.message || '更正失败'
    return
  }
  feedback.value = result.message
  experimentCode.value = correction.value.experiment_code
  await loadRounds()
}

async function changeRound(id: number, action: 'confirm' | 'revoke') {
  const result = action === 'confirm' ? await driftClient.confirmRound(id) : await driftClient.revokeRound(id, '分析员撤销该轮次')
  if (!result.ok) {
    error.value = result.message
    return
  }
  feedback.value = result.message
  await loadRounds(false)
  if (board.value) await compare()
}

async function saveRequest() {
  error.value = ''
  const result = await driftClient.createRequest({
    experiment_code: experimentCode.value,
    left_round_id: leftRoundId.value,
    right_round_id: rightRoundId.value,
  })
  if (!result.ok) {
    error.value = result.message || '看板请求保存失败'
    return
  }
  feedback.value = `${result.message}（编号 ${result.request.request_code}）`
}

async function sendOrder() {
  error.value = ''
  order.value = null
  const result = await driftClient.createOrder({
    experiment_code: experimentCode.value,
    left_round_id: leftRoundId.value,
    right_round_id: rightRoundId.value,
  })
  if (!result.ok) {
    error.value = result.message || '换组核对单送出失败'
    if (result.board) board.value = result.board
    return
  }
  order.value = result
  feedback.value = result.message
}

onMounted(async () => {
  await loadRounds()
  await compare()
})
</script>

<style scoped>
.drift-panel { background: #fff; border: 1px solid var(--border, #e4e7ec); border-radius: 10px; padding: 16px; margin: 14px 0; }
.panel-title-row, .board-controls, .control-buttons, .setup-grid { display: flex; gap: 12px; align-items: flex-end; justify-content: space-between; flex-wrap: wrap; }
.panel-title-row { align-items: flex-start; }
.panel-title-row h3, .setup-card h4, .board-result h4 { margin: 0 0 6px; }
.panel-tip { color: #667085; margin: 0; font-size: 13px; }
.setup-grid { align-items: stretch; margin: 12px 0; }
.setup-card { flex: 1 1 320px; border: 1px solid #eaecf0; border-radius: 8px; padding: 12px; display: grid; grid-template-columns: 1fr 1fr; gap: 10px; background: #fcfcfd; }
.setup-card label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.setup-card label.inline { flex-direction: row; align-items: center; grid-column: span 2; }
.setup-card .full { grid-column: span 2; }
.setup-card input, .setup-card select, .setup-card textarea, .board-controls select, .board-controls input { border: 1px solid #d0d5dd; border-radius: 6px; padding: 7px 9px; font: inherit; }
.board-controls { justify-content: flex-start; align-items: flex-end; }
.board-controls label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; min-width: 180px; }
.control-buttons { gap: 8px; }
.round-strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 10px; margin: 14px 0; }
.round-chip { border: 1px solid #d0d5dd; border-radius: 8px; padding: 10px; background: #f9fafb; }
.round-chip header { display: flex; justify-content: space-between; gap: 8px; }
.round-chip p { margin: 5px 0; font-size: 13px; }
.badge { background: #e7f0ff; color: #175cd3; border-radius: 999px; padding: 2px 8px; font-size: 12px; }
.badge[data-revoked='true'] { background: #fee4e2; color: #b42318; }
.chip-actions { display: flex; gap: 10px; }
.warning, .error-text { color: #b42318; font-size: 13px; }
.panel-feedback, .result-card, .basis-box { background: #ecfdf3; border: 1px solid #abefc6; color: #067647; border-radius: 8px; padding: 10px 12px; margin: 10px 0; }
.result-card code { color: #054f31; }
.unavailable-box { background: #fffaeb; border: 1px solid #fedf89; color: #b54708; border-radius: 8px; padding: 10px 12px; margin: 10px 0; }
.diff-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 12px; }
.diff-card { border-radius: 8px; padding: 10px; border: 1px solid; }
.diff-card ul { margin: 6px 0 0; padding-left: 18px; }
.diff-card.added { background: #f6fef9; border-color: #abefc6; }
.diff-card.exited { background: #fffbfa; border-color: #fecdca; }
.diff-card.transferred { background: #eff8ff; border-color: #b2ddff; }
.empty-inline { color: #98a2b3; list-style: none; margin-left: -18px; }
.count-rule { font-size: 13px; color: #475467; }
.health-box, .adjacent-box { border-top: 1px solid #eaecf0; margin-top: 12px; padding-top: 10px; }
.link.danger { color: #b42318; }
@media (max-width: 900px) { .diff-grid { grid-template-columns: 1fr; } }
</style>
