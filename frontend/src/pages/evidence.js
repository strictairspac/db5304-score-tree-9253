import {heading, panel} from '../components/common/heading.js';
import {entries, records} from '../components/common/records.js';
import {topic} from '../constants/project.js';
import {date, el, esc} from '../utils/dom.js';
import {submit} from '../hooks/submit.js';

function findSection(report, title) {
  return report.sections.find(section => section.title === title);
}

export function evidencePage(state, identity) {
  const current = state.evidence.find(row=>row.id===identity) || state.evidence[0];
  if (!current) return heading(topic.modules[3]) + '<p class="empty">执行完成后，可查看、复核和导出证据。</p>';
  const {report} = current;
  const exportable = Boolean(current.exportable && report.exportable);
  const metrics = Object.entries(report.metrics).map(([label,value])=>`<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join('');
  const batchSection = findSection(report, '批次摘要');
  const conclusionSection = findSection(report, '巡检结论');
  const rangeSection = findSection(report, '范围结果巡检');
  const structureSection = findSection(report, '结构不变量巡检');
  const sections = report.sections
    .filter(section => !['批次摘要','巡检结论','范围结果巡检','结构不变量巡检'].includes(section.title))
    .map(x=>panel(x.title, entries(x.rows))).join('');
  const review = current.reviewer ? `<p data-testid="reviewed">${esc(current.reviewer)} · ${esc(date(current.reviewed_at))}</p><p>${esc(current.review_note)}</p>`
    : state.session.role==='reviewer'?`<form id="review-form" data-evidence-id="${current.id}"><label>复核意见<textarea name="note" maxlength="500" required></textarea></label><button>签署复核</button></form>`
    : '<p class="note">待复核员签署</p>';
  const history = state.evidence.map(row=>[`<a href="#evidence/${row.id}">执行 ${row.run_id}</a>`, esc(row.report.summary), esc(row.reviewer || '待复核')]);
  const gateBadge = exportable
    ? '<span class="status" data-state="complete" data-testid="exportable">可导出</span>'
    : '<span class="status" data-state="failed" data-testid="locked">不可导出</span>';
  const download = exportable
    ? `<button id="download" data-id="${current.id}">导出证据</button>`
    : '<button class="secondary" disabled title="巡检未全部通过，报告已锁定">导出已锁定</button>';
  const reportBatch = (state.batches || []).find(batch => batch.batch_no === report.batch_no);
  const relatedConflicts = reportBatch
    ? (state.conflicts || []).filter(row => row.batch_id === reportBatch.id) : [];
  const conflictPanel = relatedConflicts.length ? panel('编号冲突信息', records(
    ['冲突编号','送入谱名','送入库存','已归并谱名','已归并库存','冲突批次'],
    relatedConflicts.map(row=>[esc(row.score_number), esc(row.incoming_title), esc(row.incoming_copies),
      esc(row.existing_title), esc(row.existing_copies), esc(row.batch_no)]))) : '';
  const gate = `<section class="panel" data-testid="inspection-gate"><h2>巡检闸门与可导出状态</h2>
    <p class="spread"><strong>叶页链 / 记录数 / 范围结果</strong>${gateBadge}</p>
    <p class="note">${exportable ? '叶页链、总记录数与范围结果巡检全部通过，报告可安全下载。' : '巡检存在未通过项，报告锁定，不可导出。'}</p></section>`;
  return `${heading(topic.modules[3], report.summary, download)}
    <div class="spread evidence-top"><dl class="metrics">${metrics}</dl><aside class="brief"><h2>复核签署</h2>${review}<details><summary>结果校验码</summary><code class="digest">${esc(current.digest)}</code></details></aside></div>
    ${gate}
    ${conflictPanel}
    ${batchSection ? panel('批次摘要', entries(batchSection.rows)) : ''}
    ${conclusionSection ? panel('巡检结论', entries(conclusionSection.rows)) : ''}
    ${rangeSection ? panel('范围结果巡检（叶链寻址）', entries(rangeSection.rows)) : ''}
    ${structureSection ? panel('结构不变量巡检（叶页链与记录数）', entries(structureSection.rows)) : ''}
    ${sections}<details><summary>历史证据</summary>${records(['执行','结论','复核'], history)}</details>`;
}

export function bindEvidence(api, update, fail) {
  const button = document.getElementById('download');
  if (button && !button.disabled) {
    const identity = button.dataset.id;
    button.addEventListener('click', async()=>{
      try {
        const response = await api(`/evidence/${identity}/download`, {response:true});
        const url = URL.createObjectURL(await response.blob());
        const link = el('a');
        link.href = url;
        link.download = `evidence-${identity}.json`;
        link.click();
        setTimeout(()=>URL.revokeObjectURL(url), 1000);
      } catch (error) { fail(error); }
    });
  }
  const form = document.getElementById('review-form');
  if (!form) return;
  const identity = form.dataset.evidenceId;
  submit('review-form', async data=>{
    await api(`/evidence/${identity}/review`, {method:'POST', data:{note:data.get('note')}});
    await update();
  }, fail);
}
