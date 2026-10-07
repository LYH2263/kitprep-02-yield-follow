<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'

interface BomLineRow { id: number; ingredient_name: string; qty_per_portion: number; unit: string; yield_rate: number | null }
interface DishGroup { dish_id: number; dish_name: string; dish_code: string; yield_rate: number | null; lines: BomLineRow[] }

const YIELD_MSG = '出成率必须在 0 到 1 之间（不含 0），留空表示未设置'

const groups = ref<DishGroup[]>([])
const saving = ref(false)
const error = ref('')
const notice = ref('')

function norm(v: unknown): number | null {
  if (v === '' || v === null || v === undefined) return null
  return Number(v)
}

async function load() {
  const rows = await api<any[]>('/bom')
  const map = new Map<number, DishGroup>()
  for (const r of rows) {
    if (!map.has(r.dish_id)) {
      map.set(r.dish_id, { dish_id: r.dish_id, dish_name: r.dish_name, dish_code: r.dish_code, yield_rate: r.dish_yield_rate, lines: [] })
    }
    map.get(r.dish_id)!.lines.push({
      id: r.id, ingredient_name: r.ingredient_name,
      qty_per_portion: r.qty_per_portion, unit: r.unit, yield_rate: r.yield_rate,
    })
  }
  groups.value = [...map.values()]
}

function detail(err: unknown): string {
  try {
    const parsed = JSON.parse(String((err as Error)?.message ?? err))
    if (typeof parsed?.detail === 'string') return parsed.detail
  } catch { /* 非 JSON，原样展示 */ }
  return String((err as Error)?.message ?? err)
}

async function save() {
  error.value = ''; notice.value = ''
  const lines = groups.value.flatMap(g => g.lines.map(l => ({ id: l.id, yield_rate: norm(l.yield_rate) })))
  const dishes = groups.value.map(g => ({ id: g.dish_id, yield_rate: norm(g.yield_rate) }))
  for (const item of [...lines, ...dishes]) {
    if (item.yield_rate !== null && (!(item.yield_rate > 0) || item.yield_rate > 1)) {
      error.value = YIELD_MSG
      return
    }
  }
  saving.value = true
  try {
    const res = await api<{ rewritten: unknown[] }>('/bom/yield-rates', {
      method: 'PUT', body: JSON.stringify({ lines, dishes }),
    })
    notice.value = res.rewritten?.length
      ? '已保存出成率，当前备料单已按新率整张重写'
      : '已保存出成率'
    await load()
  } catch (e) {
    error.value = detail(e)
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <h1>BOM 定额</h1>
  <p class="sub">出品率 / 用料出成率 · 留空 = 1（未写过）· 保存后当前备料单整张按新率重写，历史单不动</p>
  <div class="card" style="max-width:760px">
    <div style="display:flex;gap:0.6rem;align-items:center;flex-wrap:wrap;margin-bottom:0.5rem">
      <button class="btn" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存出成率' }}</button>
      <span v-if="notice" class="badge badge-ok">{{ notice }}</span>
      <span v-if="error" class="badge badge-bad">{{ error }}</span>
    </div>
    <div v-for="g in groups" :key="g.dish_id" style="border-top:2px solid rgba(92,61,46,0.25);padding:0.55rem 0">
      <div style="display:flex;align-items:center;gap:0.6rem;margin-bottom:0.35rem">
        <strong>{{ g.dish_name }}</strong>
        <span class="muted" style="font-size:0.72rem">{{ g.dish_code }}</span>
        <label style="margin-left:auto;font-size:0.78rem" class="muted">
          出品率
          <input class="kp-rate-input" type="number" min="0" max="1" step="0.01"
                 v-model.number="g.yield_rate" placeholder="1">
        </label>
      </div>
      <table>
        <thead>
          <tr><th>原料</th><th>定额 / 份</th><th>单位</th><th>用料出成率</th></tr>
        </thead>
        <tbody>
          <tr v-for="l in g.lines" :key="l.id">
            <td>{{ l.ingredient_name }}</td>
            <td>{{ l.qty_per_portion }}</td>
            <td>{{ l.unit }}</td>
            <td>
              <input class="kp-rate-input" type="number" min="0" max="1" step="0.01"
                     v-model.number="l.yield_rate" placeholder="1">
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
