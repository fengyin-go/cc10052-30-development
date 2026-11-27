/**
 * AA 多轮次漂移的纯前端领域规则。
 *
 * 权威差异由后端再次核对；这里仅用于看板即时分组、计数和文案测试锚点。
 */
export type GroupName = '实验组' | '对照组' | string

export interface SampleMember {
  user_id: string
  group?: GroupName
  分组名称?: GroupName
  [key: string]: unknown
}

export interface RoundLike {
  id?: number | string | null
  round_code?: string
  轮次编码?: string
  version?: number
  版本?: number
  status?: string
  members?: SampleMember[]
  counts?: Record<string, number>
  [key: string]: unknown
}

export function canonicalGroup(value: unknown): GroupName {
  const text = String(value ?? '').trim()
  if (!text) return ''
  if (text.includes('实验') || text.includes('试验')) return '实验组'
  if (text.includes('对照')) return '对照组'
  const low = text.toLowerCase().replace(/[-_\s]/g, '')
  if (['treatment', 'treat', 'test', 'exp', 'experiment', 'a', 't'].includes(low)) return '实验组'
  if (['control', 'ctrl', 'ck', 'b', 'c'].includes(low)) return '对照组'
  return text
}

export function memberIdentity(member: SampleMember): string {
  return String(member.user_id ?? member.用户标识 ?? member.uid ?? '')
}

export function normalizeMembers(raw: unknown): SampleMember[] {
  if (!raw) return []
  const list = Array.isArray(raw)
    ? raw
    : Object.entries(raw as Record<string, unknown>).map(([user_id, group]) => ({ user_id, group }))
  const map = new Map<string, SampleMember>()
  for (const item of list as any[]) {
    const member: SampleMember = typeof item === 'string' || typeof item === 'number'
      ? { user_id: String(item) }
      : { ...item, user_id: String(item.user_id ?? item.用户标识 ?? item.uid ?? '') }
    if (!member.user_id) continue
    member.group = canonicalGroup(member.group ?? member.分组名称 ?? member.group_name)
    map.set(member.user_id, member)
  }
  return [...map.values()].sort((a, b) => memberIdentity(a).localeCompare(memberIdentity(b)))
}

export function countGroups(members: SampleMember[]): Record<'实验组' | '对照组' | '未分组', number> {
  const counts = { 实验组: 0, 对照组: 0, 未分组: 0 }
  for (const member of normalizeMembers(members)) {
    const group = canonicalGroup(member.group ?? member.分组名称)
    if (group === '实验组' || group === '对照组') counts[group] += 1
    else counts.未分组 += 1
  }
  return counts
}

export function diffMembers(left: SampleMember[], right: SampleMember[]) {
  const oldMap = new Map(normalizeMembers(left).map((m) => [memberIdentity(m), m]))
  const newMap = new Map(normalizeMembers(right).map((m) => [memberIdentity(m), m]))
  const added: any[] = []
  const exited: any[] = []
  const transferred: any[] = []
  const unchanged: any[] = []

  for (const user_id of [...new Set([...oldMap.keys(), ...newMap.keys()])].sort()) {
    const before = oldMap.get(user_id)
    const after = newMap.get(user_id)
    if (!before && after) {
      added.push({ user_id, to_group: after.group, change_type: '新增' })
    } else if (before && !after) {
      exited.push({ user_id, from_group: before.group, change_type: '退出' })
    } else if (before && after) {
      const fromGroup = canonicalGroup(before.group)
      const toGroup = canonicalGroup(after.group)
      if (fromGroup !== toGroup) {
        transferred.push({ user_id, from_group: fromGroup, to_group: toGroup, change_type: '只换组的同一成员' })
      } else {
        unchanged.push({ user_id, group: fromGroup })
      }
    }
  }

  return {
    added,
    exited,
    transferred,
    unchanged,
    新增: added,
    退出: exited,
    只换组的同一成员: transferred,
    summary: {
      added_count: added.length,
      exited_count: exited.length,
      transferred_count: transferred.length,
      transition_count: transferred.length,
      identity_change_count: added.length + exited.length + transferred.length,
      计数口径: '同一成员换组只计一次转换；不得拆成一次退出和一次新增',
    },
  }
}

export function missingGroups(counts: Record<string, number>): string[] {
  return ['实验组', '对照组'].filter((group) => Number(counts?.[group] ?? 0) === 0)
}

export function canCheckSameRoundRatio(round: RoundLike): boolean {
  const counts = (round.counts ?? round.group_counts ?? round.组内人数 ?? countGroups(normalizeMembers(round.members))) as Record<string, number>
  return missingGroups(counts).length === 0
}

export function adjacentConfirmedRounds(rounds: RoundLike[]) {
  const confirmed = rounds
    .filter((round) => round.status === '已确认' && round.revoked !== true)
    .sort((a, b) => Number(a.序号 ?? a.sequence ?? 0) - Number(b.序号 ?? b.sequence ?? 0)
      || Number(a.版本 ?? a.version ?? 1) - Number(b.版本 ?? b.version ?? 1))
  return confirmed.slice(1).map((right, index) => ({ left: confirmed[index], right }))
}

/** 前端即时预览；正式结果以后端 /api/aa-drift/board 为准。 */
export function buildDriftBoard(left: RoundLike, right: RoundLike) {
  const leftMembers = normalizeMembers(left.members)
  const rightMembers = normalizeMembers(right.members)
  return {
    left,
    right,
    diff: diffMembers(leftMembers, rightMembers),
    adjacent_confirmed: adjacentConfirmedRounds([left, right]),
  }
}

export const compareRounds = buildDriftBoard
export const compareSampleRounds = buildDriftBoard
export const getDriftBoard = buildDriftBoard

export default {
  canonicalGroup,
  normalizeMembers,
  countGroups,
  diffMembers,
  missingGroups,
  canCheckSameRoundRatio,
  adjacentConfirmedRounds,
  buildDriftBoard,
}
