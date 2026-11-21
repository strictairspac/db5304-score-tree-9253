import {heading, panel} from '../components/common/heading.js';
import {entries, records} from '../components/common/records.js';
import {badge} from '../components/common/status.js';
import {date, esc} from '../utils/dom.js';
import {topic} from '../constants/project.js';

export function casesPage(state, identity) {
  const {spec, session, cases, runs, batches, conflicts} = state;
  const selected = cases.find(row=>row.id===identity) || cases[0];
  const operator = session.role==='operator';
  const batchMap = new Map((batches || []).map(row=>[row.case_id, row]));
  const rows = cases.map(row=>{
    const batch = batchMap.get(row.id);
    return [`<a href="#cases/${row.id}" ${row.id===selected?.id?'aria-current="true"':''}>${esc(row.title)}</a>`,
      esc(row.author), batch ? badge(batch.status) : '未登记', esc(date(row.created_at))];
  });
  const instruction = selected ? `<h2>${esc(selected.title)}</h2><p>${esc(spec.guidance)}</p>` : '';
  const selectedBatch = selected ? batchMap.get(selected.id) : null;
  const selectedConflicts = selectedBatch
    ? (conflicts || []).filter(row=>row.batch_id === selectedBatch.id) : [];
  const input = selected ? Object.entries(selected.payload).map(([key, value])=>{
    const label = spec.field_labels[key] || key;
    const isRows = Array.isArray(value) && value.every(x=>x && typeof x === 'object' && !Array.isArray(x));
    return panel(label, isRows ? entries(value.slice(0,10), spec.field_labels) + (value.length>10?`<p class="note">显示前 10 条，共 ${value.length} 条。</p>`:'') : `<pre>${esc(value)}</pre>`);
  }).join('') : '';
  const conflictPanel = selectedConflicts.length ? panel('编号冲突信息', records(
    ['冲突编号','送入谱名','送入库存','已归并谱名','已归并库存'],
    selectedConflicts.map(row=>[esc(row.score_number), esc(row.incoming_title), esc(row.incoming_copies),
      esc(row.existing_title), esc(row.existing_copies)]))) : '';
  return `${heading(topic.modules[0], spec.summary, operator?'<a class="button" href="#editor">建立档案</a>':'')}
    <div class="spread"><section aria-label="档案目录">${records([spec.entity_labels[0], '经办', '批次归并', '建立时间'], rows, '尚未建立档案。经办员可以从演示资料建立第一份。')}</section>
    <aside class="brief">${instruction || `<h2>${esc(spec.customer)}</h2>`}${selected?`<p class="note">该档案记录 ${runs.filter(row=>row.case_id===selected.id).length} 次执行。</p>`:''}${selected&&operator?`<a href="#editor/${selected.id}">复制为新档案</a>`:''}</aside></div>
    ${conflictPanel}
    ${input ? `<div class="inspection">${input}</div>`:''}`;
}
