/** @typedef {{id:number, title:string, payload:object, author:string}} BusinessCase */
/** @typedef {{id:number, case_id:number, status:'queued'|'running'|'complete'|'failed'|'rejected', attempt_count:number, batch_id:number|null, error:string|null}} Run */
/** @typedef {{id:number, run_id:number, digest:string, inspection_passed:boolean, exportable:boolean, reviewer:string|null, report:{batch_no:string, summary:string, exportable:boolean, inspection_passed:boolean, metrics:object, sections:Array}}} Evidence */
/** @typedef {{id:number, batch_no:string, fingerprint:string, status:'accepted'|'rejected'|'failed'|'queued', score_count:number, copies_total:number, owner:string}} CatalogBatch */
/** @typedef {{id:number, batch_id:number, score_number:number, incoming_title:string, incoming_copies:number, existing_batch_id:number, existing_title:string, existing_copies:number, batch_no:string}} BatchConflict */
