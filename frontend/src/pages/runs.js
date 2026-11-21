import {heading, panel} from '../components/common/heading.js';
import {records} from '../components/common/records.js';
import {badge} from '../components/common/status.js';
import {batchStatusLabels, statusLabels} from '../constants/workflow.js';
import {topic} from '../constants/project.js';
import {date, esc} from '../utils/dom.js';

export function runsPage(state, identity) {
  const selected = state.runs.find(row=>row.id===identity) || state.runs[0];
  const cases = new Map(state.cases.map(row=>[row.id, row.title]));
  const batchMap = new Map((state.batches || []).map(row=>[row.id, row]));
  const rows = state.runs.map(row=>{
    const batch = row.batch_id ? batchMap.get(row.batch_id) : null;
    return [`<a href="#runs/${row.id}">${esc(cases.get(row.case_id) || row.case_id)}</a>`,
      batch ? esc(batch.batch_no) : '—', badge(row.status), esc(row.owner), esc(date(row.created_at))];
  });
  const result = state.evidence.find(row=>row.run_id===selected?.id);
  const active = selected && ['queued','running'].includes(selected.status);
  const canRetry = selected && ['failed','rejected'].includes(selected.status) && state.session.role==='operator';
  const selectedBatch = selected?.batch_id ? batchMap.get(selected.batch_id) : null;
  const selectedConflicts = selectedBatch
    ? (state.conflicts || []).filter(row=>row.batch_id === selectedBatch.id) : [];
  const conflictRows = selectedConflicts.map(row=>[esc(row.score_number),
    `${esc(row.incoming_title)} / ${esc(row.incoming_copies)} 份`,
    `${esc(row.existing_title)} / ${esc(row.existing_copies)} 份`]);
  const detail = selected ? `<h2>${esc(cases.get(selected.case_id) || selected.case_id)}</h2>
    <p data-testid="run-status">${badge(selected.status)}</p>
    <dl><dt>批次号</dt><dd>${esc(selectedBatch?.batch_no || '—')}</dd>
    <dt>批次归并状态</dt><dd>${esc(selectedBatch ? (batchStatusLabels[selectedBatch.status] || selectedBatch.status) : '—')}</dd>
    <dt>尝试次数</dt><dd>${esc(selected.attempt_count ?? 0)}</dd>
    <dt>启动时间</dt><dd>${esc(date(selected.started_at))}</dd>
    <dt>完成时间</dt><dd>${esc(date(selected.finished_at))}</dd></dl>
    ${selected.error ? `<p class="error" data-testid="run-error">${esc(selected.error)}</p>` : ''}
    ${selectedConflicts.length ? panel('编号冲突明细（整批拒绝，未归并库存）',
      records(['冲突编号','送入谱名 / 库存','已归并谱名 / 库存'], conflictRows)) : ''}
    ${active?'<p class="note">后台处理中，记录会自动刷新。崩溃或停顿时可由其他执行者接管继续。</p>':''}
    ${canRetry?'<form id="retry-form"><button type="submit">接管并重试执行</button><p class="note">重试复用本执行记录，不会新增证据；冲突批次须修正编号或库存后以新批次提交。</p></form>':''}
    ${result?`<a class="button" href="#evidence/${result.id}">查看业务证据</a>`:''}` : '<h2>执行记录</h2><p>从档案创建一条执行记录后，可在此查看进度。</p>';
  const audit = state.audit.filter(x=>selected && (
    x.reference===String(selected.id)
    || (selected.batch_id && x.reference===String(selected.batch_id)))
    && ['enqueue', 'complete', 'failed', 'retry', 'reject_batch', 'duplicate_batch'].includes(x.action));
  return `${heading(topic.modules[2], `${state.spec.entity_labels[1]}与后台处理进度`, '<button class="secondary" type="button" id="refresh">刷新记录</button>')}
    <div class="spread"><section>${records(['档案','批次号','状态','经办','提交时间'], rows, '暂无执行记录。')}</section><aside class="brief">${detail}</aside></div>
    ${audit.length?panel('操作记录', records(['操作者','操作','时间'], audit.map(x=>[esc(x.actor),esc(statusLabels[x.action]||x.action),esc(date(x.created_at))]))):''}`;
}

export function bindRuns(api, update, fail) {
  const form = document.getElementById('retry-form');
  if (!form) return;
  const {id} = selectedId();
  form.addEventListener('submit', async event=>{
    event.preventDefault();
    try {
      await api(`/runs/${id}/retry`, {method:'POST'});
      await update();
    } catch (error) { fail(error); }
  });
}

function selectedId() {
  const [, raw] = (location.hash.slice(1) || '').split('/');
  return {id: Number(raw) || 0};
}
