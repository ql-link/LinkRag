import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { useToast } from '@/contexts/ToastContext';
import { updateDataset } from '@/services/datasets';
import type { Dataset } from '@/types';

import { DeleteDatasetDialog } from './DeleteDatasetDialog';
import { DisableDatasetDialog } from './DisableDatasetDialog';
import { EditDatasetDialog } from './EditDatasetDialog';

export type DatasetAction = 'edit' | 'disable' | 'delete';

/**
 * 知识库操作的统一编排：编辑 / 停用 / 启用 / 删除，列表页与详情页共用。
 * 停用成功后给出带「撤销」的提示（C13）。
 */
export function useDatasetActions(opts: { afterDelete?: () => void } = {}) {
  const toast = useToast();
  const navigate = useNavigate();
  const [editing, setEditing] = useState<Dataset | null>(null);
  const [disabling, setDisabling] = useState<Dataset | null>(null);
  const [deleting, setDeleting] = useState<Dataset | null>(null);

  const enable = async (ds: Dataset) => {
    await updateDataset(ds.id, { status: 'enabled' });
    toast(`已重新启用「${ds.name}」`, { tone: 'success' });
  };

  const open = (action: DatasetAction, ds: Dataset) => {
    if (action === 'edit') setEditing(ds);
    if (action === 'disable') setDisabling(ds);
    if (action === 'delete') setDeleting(ds);
  };

  const dialogs = (
    <>
      <EditDatasetDialog
        dataset={editing}
        onClose={() => setEditing(null)}
        onRequestDisable={(ds) => {
          setEditing(null);
          setDisabling(ds);
        }}
      />
      <DisableDatasetDialog
        dataset={disabling}
        onClose={() => setDisabling(null)}
        onDisabled={(ds) => {
          setDisabling(null);
          toast(`已停用「${ds.name}」`, {
            tone: 'success',
            action: { label: '撤销', onClick: () => void updateDataset(ds.id, { status: 'enabled' }) },
            icon: undefined,
          });
        }}
      />
      <DeleteDatasetDialog
        dataset={deleting}
        onClose={() => setDeleting(null)}
        onSuggestDisable={(ds) => {
          setDeleting(null);
          setDisabling(ds);
        }}
        onDeleted={(ds) => {
          setDeleting(null);
          toast(`已删除「${ds.name}」`, { tone: 'success' });
          if (opts.afterDelete) opts.afterDelete();
          else navigate('/datasets');
        }}
      />
    </>
  );

  return { open, enable, dialogs };
}

