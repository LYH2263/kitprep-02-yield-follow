<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const tree = ref<any[]>([])
const data = ref<any>(null)
const shortages = ref<any[]>([])
const orders = ref<any[]>([])
const loading = ref(false)
const error = ref('')

async function load() {
  // 只读已落库的当前有效单，禁止打开备料台按定义现算
  try { data.value = await api('/prep/latest?order_id=1') } catch { data.value = null }
  try {
    const res = await api('/prep/shortages?order_id=1')
    shortages.value = res.shortages || []
  } catch { shortages.value = [] }
}

async function run() {
  loading.value = true
  error.value = ''
  try {
    await api('/prep/run?order_id=1', { method: 'POST' })
    await load()
  } catch (e: any) {
    error.value = String(e?.message ?? e)
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  tree.value = await api('/bom/tree')
  orders.value = await api('/orders')
  await load()
})
</script>
<template>
  <h1>备料工作台</h1>
  <p class="sub">左 BOM 树 · 中备料表 · 右缺料便利贴 · 顶栏订单芯片 · 只读已落库备料单</p>
  <div class="kp-chips" style="margin-bottom:0.75rem" v-if="orders.length">
    <span v-for="o in orders" :key="o.id" class="kp-chip" style="cursor:default">
      {{ o.code }} · {{ o.outlet }}
    </span>
  </div>
  <button class="btn" :disabled="loading" @click="run">{{ loading ? '生成中…' : '生成备料单' }}</button>
  <span v-if="error" class="badge badge-bad" style="margin-left:0.6rem">{{ error }}</span>
  <div class="kp-workbench" style="margin-top:0.85rem">
    <aside class="kp-bom-tree">
      <h2>菜品 / BOM</h2>
      <div v-for="d in tree" :key="d.code" class="kp-dish-node">
        <strong>{{ d.dish }}</strong>
        <span style="font-size:0.7rem;color:#8a8078">{{ d.code }}</span>
        <ul>
          <li v-for="(c,i) in d.children" :key="i">
            {{ c.ingredient }} · {{ c.qty }} {{ c.unit }}
            <template v-if="c.yield_rate != null">· 出成率 {{ c.yield_rate }}</template>
          </li>
        </ul>
      </div>
    </aside>
    <section class="kp-worksheet" v-if="data">
      <h2>备料单 #{{ data.id }} · {{ data.order?.code }} · {{ data.order?.outlet }}</h2>
      <table>
        <thead><tr><th>原料</th><th>需求</th><th>库存</th><th>单位</th></tr></thead>
        <tbody>
          <tr v-for="l in data.prep_lines" :key="l.ingredient_id">
            <td>{{ l.ingredient_name }}</td><td>{{ l.need_qty }}</td><td>{{ l.stock_qty }}</td><td>{{ l.unit }}</td>
          </tr>
        </tbody>
      </table>
    </section>
    <section class="kp-worksheet" v-else>
      <h2>备料单</h2>
      <p class="muted" style="font-size:0.85rem">
        尚未生成备料单。这里只展示已落库的当前有效单，请点击「生成备料单」落库。
      </p>
    </section>
    <aside class="kp-shortage-sticky">
      <h2>⚠ 缺料便利贴</h2>
      <div v-for="r in shortages" :key="r.ingredient_id" class="kp-shortage-item">
        <span>{{ r.ingredient_name }}</span>
        <span class="kp-qty">−{{ r.shortage }} {{ r.unit }}</span>
      </div>
      <p v-if="!shortages.length" style="font-size:0.8rem;margin:0.5rem 0 0">暂无缺料</p>
    </aside>
  </div>
</template>
