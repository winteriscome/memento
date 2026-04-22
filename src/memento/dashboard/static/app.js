/* ═══ Memento Dashboard — Vue 3 SPA ═══ */

const { createApp, ref, computed, onMounted, watch, nextTick } = Vue;
const { createRouter, createWebHashHistory } = VueRouter;

/* ── Helpers ── */

function strengthColor(s) {
  if (s > 0.6) return 'var(--primary)';
  if (s > 0.3) return 'var(--warning)';
  return 'var(--danger)';
}

function debounce(fn, ms) {
  let t;
  return function (...args) { clearTimeout(t); t = setTimeout(() => fn.apply(this, args), ms); };
}

async function api(path, opts) {
  try {
    const res = await fetch('/api' + path, opts);
    if (!res.ok) throw new Error('HTTP ' + res.status);
    if (res.status === 204) return null;
    return await res.json();
  } catch (e) {
    console.error('[API]', path, e);
    return null;
  }
}

function fmtTime(iso) {
  if (!iso) return '-';
  const d = new Date(iso);
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

/* ── MemoriesView ── */

const MemoriesView = {
  template: `
<div class="container">
  <!-- Stats -->
  <div class="stats-bar">
    <div class="stat-card">
      <div class="stat-value">{{ status.active ?? '-' }}</div>
      <div class="stat-label">活跃记忆</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">{{ status.unverified_agent ?? '-' }}</div>
      <div class="stat-label">待验证</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">{{ status.total_sessions ?? '-' }}</div>
      <div class="stat-label">会话数</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">{{ status.cognitive_debt_count ?? '-' }}</div>
      <div class="stat-label">认知债务</div>
    </div>
  </div>

  <!-- Toolbar -->
  <div class="toolbar">
    <input type="text" v-model="searchInput" placeholder="搜索记忆..." />
    <select v-model="filterType">
      <option value="">全部类型</option>
      <option v-for="t in types" :key="t" :value="t">{{ t }}</option>
    </select>
    <select v-model="filterOrigin">
      <option value="">全部来源</option>
      <option value="human">human</option>
      <option value="agent">agent</option>
    </select>
    <select v-model="sortBy">
      <option value="created_at">创建时间</option>
      <option value="strength">强度</option>
      <option value="access_count">访问次数</option>
    </select>
  </div>

  <!-- List -->
  <div v-if="loading" class="loading">加载中...</div>
  <div v-else-if="engrams.length === 0" class="empty">暂无记忆</div>
  <div v-else class="card-list">
    <div v-for="e in engrams" :key="e.id"
         class="memory-card" :class="{ dimmed: e.strength < 0.3 }">
      <div class="card-header">
        <span class="badge badge-primary">{{ e.type }}</span>
        <span class="badge" :class="e.origin === 'agent' ? 'badge-warning' : 'badge-success'">{{ e.origin }}</span>
        <span v-if="e.importance" class="badge badge-muted">{{ e.importance }}</span>
        <span v-if="e.verified" class="badge badge-success">已验证</span>
      </div>
      <div class="card-content">{{ e.content }}</div>
      <div v-if="e.tags && e.tags.length" class="card-header" style="margin-bottom:8px">
        <span v-for="tag in e.tags" :key="tag" class="tag">{{ tag }}</span>
      </div>
      <div class="card-meta">
        <div class="strength-bar">
          <span style="font-size:12px;color:var(--text-muted)">强度</span>
          <div class="bar-track">
            <div class="bar-fill" :style="{ width: (e.strength*100)+'%', background: strengthColor(e.strength) }"></div>
          </div>
          <span class="bar-label" :style="{ color: strengthColor(e.strength) }">{{ (e.strength*100).toFixed(0) }}%</span>
        </div>
        <span>访问 {{ e.access_count ?? 0 }}</span>
        <span>{{ fmtTime(e.created_at) }}</span>
      </div>
      <div class="card-actions">
        <button v-if="e.origin === 'agent' && !e.verified" class="btn btn-success" @click="verify(e)">验证</button>
        <button class="btn btn-outline" @click="confirmPin(e)">📌 Pin</button>
        <button class="btn btn-danger" @click="confirmDelete(e)">删除</button>
      </div>
    </div>
  </div>

  <!-- Delete Modal -->
  <div v-if="delTarget" class="modal-overlay" @click.self="delTarget=null">
    <div class="modal-box">
      <h3>确认删除</h3>
      <p>确定要标记删除这条记忆吗？将在下次 epoch 整合时生效。</p>
      <div class="modal-actions">
        <button class="btn btn-outline" @click="delTarget=null">取消</button>
        <button class="btn btn-danger" @click="doDelete">删除</button>
      </div>
    </div>
  </div>

  <!-- Pin Modal -->
  <div v-if="pinTarget" class="modal-overlay" @click.self="pinTarget=null">
    <div class="modal-box">
      <h3>设置 Rigidity（防遗忘）</h3>
      <p>Rigidity 越高，记忆越不容易被自然衰减遗忘。</p>
      <p style="font-size:12px;color:var(--text-muted);margin-bottom:12px">{{ pinTarget.content }}</p>
      <div style="margin-bottom:16px">
        <select v-model="pinRigidity" style="padding:6px 12px;border:1px solid var(--border);border-radius:6px;width:100%">
          <option value="0">0.0 — 无保护（默认）</option>
          <option value="0.3">0.3 — 轻度保护</option>
          <option value="0.5">0.5 — 中度保护</option>
          <option value="0.8">0.8 — 高度保护</option>
          <option value="1">1.0 — 完全钉住</option>
        </select>
      </div>
      <div class="modal-actions">
        <button class="btn btn-outline" @click="pinTarget=null">取消</button>
        <button class="btn btn-primary" @click="doPin">确认设置</button>
      </div>
    </div>
  </div>
</div>`,

  setup() {
    const types = ['fact', 'decision', 'insight', 'convention', 'debugging', 'preference'];
    const status = ref({});
    const engrams = ref([]);
    const loading = ref(true);
    const searchInput = ref('');
    const searchQuery = ref('');
    const filterType = ref('');
    const filterOrigin = ref('');
    const sortBy = ref('created_at');
    const delTarget = ref(null);
    const pinTarget = ref(null);
    const pinRigidity = ref('0.5');

    const debouncedSearch = debounce((v) => { searchQuery.value = v; }, 300);
    watch(searchInput, (v) => debouncedSearch(v));

    async function loadStatus() {
      const d = await api('/status');
      if (d) status.value = d;
    }

    async function loadEngrams() {
      loading.value = true;
      const params = new URLSearchParams();
      if (searchQuery.value) params.set('q', searchQuery.value);
      if (filterType.value) params.set('type', filterType.value);
      if (filterOrigin.value) params.set('origin', filterOrigin.value);
      params.set('sort', sortBy.value);
      params.set('order', 'desc');
      params.set('limit', '50');
      const d = await api('/engrams?' + params.toString());
      engrams.value = d ? (d.engrams || d) : [];
      loading.value = false;
    }

    watch([searchQuery, filterType, filterOrigin, sortBy], () => loadEngrams());

    async function verify(e) {
      await api('/engrams/' + e.id + '/verify', { method: 'POST' });
      e.verified = true;
    }

    function confirmDelete(e) { delTarget.value = e; }

    async function doDelete() {
      if (!delTarget.value) return;
      await api('/engrams/' + delTarget.value.id, { method: 'DELETE' });
      engrams.value = engrams.value.filter(e => e.id !== delTarget.value.id);
      delTarget.value = null;
    }

    function confirmPin(e) { pinTarget.value = e; pinRigidity.value = '0.5'; }

    async function doPin() {
      if (!pinTarget.value) return;
      await api('/engrams/' + pinTarget.value.id + '/pin', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rigidity: parseFloat(pinRigidity.value) }),
      });
      pinTarget.value.rigidity = parseFloat(pinRigidity.value);
      pinTarget.value = null;
    }

    onMounted(() => { loadStatus(); loadEngrams(); });

    return {
      types, status, engrams, loading,
      searchInput, filterType, filterOrigin, sortBy,
      delTarget, pinTarget, pinRigidity,
      verify, confirmDelete, doDelete, confirmPin, doPin,
      strengthColor, fmtTime,
    };
  }
};

/* ── SessionsView ── */

const SessionsView = {
  template: `
<div class="container">
  <div class="toolbar">
    <input type="text" v-model="project" placeholder="按项目过滤..." />
  </div>

  <div v-if="loading" class="loading">加载中...</div>
  <div v-else-if="sessions.length === 0" class="empty">暂无会话</div>
  <div v-else class="card-list">
    <div v-for="s in sessions" :key="s.id" class="session-card" @click="toggle(s)">
      <div class="session-header">
        <div>
          <strong>{{ s.project || '未知项目' }}</strong>
          <span style="margin-left:8px;font-size:13px;color:var(--text-muted)">{{ s.id ? s.id.slice(0,8) : '' }}</span>
        </div>
        <span class="badge" :class="s.status === 'active' ? 'badge-success' : 'badge-muted'">{{ s.status || 'ended' }}</span>
      </div>
      <div style="font-size:13px;color:var(--text-muted)">
        {{ fmtTime(s.started_at) }} ~ {{ fmtTime(s.ended_at) }}
      </div>
      <div v-if="expanded === s.id" class="session-detail">
        <div v-if="detail">
          <p v-if="detail.summary"><strong>摘要：</strong>{{ detail.summary }}</p>
          <p v-if="detail.task"><strong>任务：</strong>{{ detail.task }}</p>
          <p v-if="detail.event_counts"><strong>事件统计：</strong>
            <span v-for="(v,k) in detail.event_counts" :key="k" class="tag" style="margin-right:4px">{{ k }}: {{ v }}</span>
          </p>
        </div>
        <div v-else class="loading">加载中...</div>
      </div>
    </div>
  </div>
</div>`,

  setup() {
    const sessions = ref([]);
    const loading = ref(true);
    const project = ref('');
    const expanded = ref(null);
    const detail = ref(null);

    async function load() {
      loading.value = true;
      const params = new URLSearchParams();
      if (project.value) params.set('project', project.value);
      params.set('limit', '50');
      const d = await api('/sessions?' + params.toString());
      sessions.value = d ? (d.sessions || d) : [];
      loading.value = false;
    }

    const debouncedLoad = debounce(() => load(), 300);
    watch(project, () => debouncedLoad());

    async function toggle(s) {
      if (expanded.value === s.id) { expanded.value = null; detail.value = null; return; }
      expanded.value = s.id;
      detail.value = null;
      const d = await api('/sessions/' + s.id);
      if (d) detail.value = d;
    }

    onMounted(() => load());

    return { sessions, loading, project, expanded, detail, toggle, fmtTime };
  }
};

/* ── SystemView ── */

const SystemView = {
  template: `
<div class="container">
  <!-- Status Overview -->
  <div class="stats-bar">
    <div class="stat-card">
      <div class="stat-value">{{ status.total ?? '-' }}</div>
      <div class="stat-label">总记忆数</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">{{ status.active ?? '-' }}</div>
      <div class="stat-label">活跃记忆</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">{{ status.forgotten ?? '-' }}</div>
      <div class="stat-label">已遗忘</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">{{ embeddingPct }}</div>
      <div class="stat-label">嵌入覆盖率</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">{{ status.pending_capture ?? '-' }}</div>
      <div class="stat-label">待处理采集</div>
    </div>
  </div>

  <!-- Epoch History -->
  <h2 class="section-title">Epoch 历史</h2>
  <table class="data-table">
    <thead><tr><th>ID</th><th>模式</th><th>状态</th><th>提交时间</th></tr></thead>
    <tbody>
      <tr v-if="epochs.length===0"><td colspan="4" style="text-align:center;color:var(--text-muted)">暂无记录</td></tr>
      <tr v-for="e in epochs" :key="e.id">
        <td>{{ e.id ? e.id.slice(0,8) : '-' }}</td>
        <td><span class="badge badge-muted">{{ e.mode }}</span></td>
        <td><span class="badge" :class="e.status==='committed'?'badge-success':'badge-warning'">{{ e.status }}</span></td>
        <td>{{ fmtTime(e.committed_at) }}</td>
      </tr>
    </tbody>
  </table>

  <!-- Cognitive Debt -->
  <h2 class="section-title">认知债务</h2>
  <table class="data-table">
    <thead><tr><th>类型</th><th>描述</th><th>严重度</th></tr></thead>
    <tbody>
      <tr v-if="debts.length===0"><td colspan="3" style="text-align:center;color:var(--text-muted)">无债务</td></tr>
      <tr v-for="(d,i) in debts" :key="i">
        <td><span class="badge badge-warning">{{ d.type }}</span></td>
        <td>{{ d.description || d.message || '-' }}</td>
        <td>{{ d.severity || '-' }}</td>
      </tr>
    </tbody>
  </table>

  <!-- Pending Captures -->
  <h2 class="section-title">待处理采集 (L2)</h2>
  <table class="data-table">
    <thead><tr><th>内容</th><th>类型</th><th>来源</th><th>创建时间</th></tr></thead>
    <tbody>
      <tr v-if="captures.length===0"><td colspan="4" style="text-align:center;color:var(--text-muted)">暂无</td></tr>
      <tr v-for="c in captures" :key="c.id">
        <td style="max-width:400px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ c.content }}</td>
        <td><span class="badge badge-primary">{{ c.type }}</span></td>
        <td><span class="badge" :class="c.origin==='agent'?'badge-warning':'badge-success'">{{ c.origin }}</span></td>
        <td>{{ fmtTime(c.created_at) }}</td>
      </tr>
    </tbody>
  </table>

  <!-- Trigger Epoch -->
  <button class="btn btn-primary" @click="showEpochModal=true" style="margin-top:8px">触发 Epoch 整合</button>

  <!-- Epoch Modal -->
  <div v-if="showEpochModal" class="modal-overlay" @click.self="showEpochModal=false">
    <div class="modal-box">
      <h3>触发 Epoch</h3>
      <p>选择整合模式并确认执行。</p>
      <div style="margin-bottom:16px">
        <select v-model="epochMode" style="padding:6px 12px;border:1px solid var(--border);border-radius:var(--radius)">
          <option value="full">full</option>
          <option value="light">light</option>
        </select>
      </div>
      <div class="modal-actions">
        <button class="btn btn-outline" @click="showEpochModal=false">取消</button>
        <button class="btn btn-primary" @click="triggerEpoch">确认执行</button>
      </div>
    </div>
  </div>
</div>`,

  setup() {
    const status = ref({});
    const epochs = ref([]);
    const debts = ref([]);
    const captures = ref([]);
    const showEpochModal = ref(false);
    const epochMode = ref('full');

    const embeddingPct = computed(() => {
      const s = status.value;
      if (!s.total || s.with_embedding == null) return '-';
      return Math.round((s.with_embedding / s.total) * 100) + '%';
    });

    async function loadAll() {
      const [st, ep, dt, cp] = await Promise.all([
        api('/status'),
        api('/epoch/history'),
        api('/epoch/debt'),
        api('/captures/pending'),
      ]);
      if (st) status.value = st;
      epochs.value = ep ? (ep.epochs || ep) : [];
      debts.value = dt ? (dt.debts || dt) : [];
      captures.value = cp ? (cp.captures || cp) : [];
    }

    async function triggerEpoch() {
      await api('/epoch/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: epochMode.value }),
      });
      showEpochModal.value = false;
      loadAll();
    }

    onMounted(() => loadAll());

    return {
      status, epochs, debts, captures,
      embeddingPct, showEpochModal, epochMode,
      triggerEpoch, fmtTime,
    };
  }
};

/* ── Router & App ── */

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', component: MemoriesView },
    { path: '/sessions', component: SessionsView },
    { path: '/system', component: SystemView },
  ],
});

const App = {
  template: `
<div>
  <nav class="nav">
    <router-link to="/" class="nav-brand">Memento</router-link>
    <div class="nav-links">
      <router-link to="/" active-class="router-link-active" exact>记忆</router-link>
      <router-link to="/sessions" active-class="router-link-active">会话</router-link>
      <router-link to="/system" active-class="router-link-active">系统</router-link>
    </div>
  </nav>
  <router-view />
</div>`
};

const app = createApp(App);
app.use(router);
app.mount('#app');
