export const roleLabels = {operator:'经办员', reviewer:'复核员', viewer:'观察员'};
export const statusLabels = {
  queued:'排队中', running:'执行中', complete:'已完成', failed:'执行失败', rejected:'冲突拒绝',
  enqueue:'提交执行', retry:'接管重试', reject_batch:'冲突拒绝', duplicate_batch:'重复批次复用',
};
export const batchStatusLabels = {accepted:'已归并', rejected:'冲突拒绝', failed:'执行失败', queued:'排队中'};
