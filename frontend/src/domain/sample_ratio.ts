/** 样本量核对领取冲突、版次选择与轮次追溯的纯领域规则。 */

export type Resolution = 'original' | 'corrected' | 'current'

const ORIGINAL = new Set(['original', 'pinned', 'submitted', 'old', 'v1', '原', '原版', '原提交版', '原提交', '旧版', '0.6'])
const CURRENT = new Set(['corrected', 'current', 'latest', 'new', 'v2', '更正', '更正后', '更正版', '当前', '当前版', '新版', '0.5'])

export function normalizeResolution(value: unknown): Resolution | null {
  if (!value) return null
  if (typeof value === 'object') {
    const candidate = (value as Record<string, unknown>).choice
      ?? (value as Record<string, unknown>).resolution
      ?? (value as Record<string, unknown>).adopt
      ?? (value as Record<string, unknown>).采用版次
    return normalizeResolution(candidate)
  }
  const text = String(value).trim().toLowerCase().replace(/\s+/g, '')
  if (CURRENT.has(text) || text.includes('更正') || text.includes('当前')) return 'current'
  if (ORIGINAL.has(text) || text.includes('原') || text.includes('旧')) return 'original'
  return null
}

export function ratioFromCounts(treatment: number, control: number): number | null {
  const total = treatment + control
  return total > 0 ? Math.round((treatment / total) * 10000) / 10000 : null
}

export function ratioCheck(treatment: number, control: number, planned = 0.5, threshold = 0.05) {
  if (treatment <= 0 || control <= 0) {
    return {
      available: false,
      eligible: false,
      reason: '缺一组的轮次仍展示计数与缺组理由，但不能进入同轮比率的样本核对',
    }
  }
  const actual = ratioFromCounts(treatment, control)!
  const offset = Math.round(Math.abs(actual - planned) * 10000) / 10000
  return {
    available: true,
    eligible: true,
    actual,
    ratio: actual,
    offset,
    status: offset > threshold ? '偏移超标' : '已核对',
  }
}

export function traceReportRounds(adoptedRounds: Array<Record<string, any>> = []) {
  return adoptedRounds.map((round) => {
    const counts = round.组内人数 ?? round.group_counts ?? round.counts ?? {}
    return {
      round: round.轮次 ?? round.round_code,
      轮次: round.轮次 ?? round.round_code,
      version: round.版本 ?? round.version,
      版本: round.版本 ?? round.version,
      group_counts: counts,
      组内人数: counts,
      actual_ratio: round.实际占比 ?? round.ratio,
      实际占比: round.实际占比 ?? round.ratio,
    }
  })
}

export const resolveClaimChoice = normalizeResolution
export const buildTrace = traceReportRounds

export default {
  normalizeResolution,
  ratioFromCounts,
  ratioCheck,
  traceReportRounds,
}
